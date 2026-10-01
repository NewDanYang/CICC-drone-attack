/******************************************************************************
 * @file       mavros_cnt.cpp
 * @brief      MAVROS 连接器实现
 * 
 * @details    实现与 MAVROS 的通信、状态管理、指令发布及安全边界保护
 * 
 * @author     郭定<1604289397@qq.com>
 * @date       2026-01-09
 *****************************************************************************/
#include "mavros_cnt.h"
#include <algorithm>
#include <tf2/LinearMath/Quaternion.h>
#include <tf2_geometry_msgs/tf2_geometry_msgs.h>



std::shared_ptr<MavRosConnect>
MavRosConnect::getInstance(std::shared_ptr<ros::NodeHandle> nh)
{
  // 使用 std::call_once 确保线程安全
  std::call_once(initFlag, [&]() {
    mavros = std::shared_ptr<MavRosConnect>(new MavRosConnect(nh));
    mavros->InitMavRosConnect();
  });
  count_++;
  return mavros;  
}

void MavRosConnect::InitMavRosConnect()
{
  std::cout << "in initail ..." << std::endl;
  if(nh_ == nullptr)
  {
    ROS_ERROR("MavRosConnect node handle is empty");
    return;
  }
  nh_->param<std::string>("fcu_state_topic", param.fcu_state_topic,
                          "mavros/state");
  nh_->param<std::string>("pos_tgt_topic", param.pos_tgt_topic,
                          "mavros/setpoint_raw/local");
  nh_->param<std::string>("odom_topic", param.fcu_odom_topic,
                          "/rflysim/uav1/local/odom");
  nh_->param<std::string>("set_mode_service", param.set_mode_service,
                          "mavros/set_mode");
  nh_->param<std::string>("arm_service", param.arm_service,
                          "mavros/cmd/arming");

  fcu_state_sub = nh_->subscribe<mavros_msgs::State>(
    param.fcu_state_topic, 10,
    bind(&MavRosConnect::FcuStateCallback, mavros, _1));

  fcu_odom_sub = nh_->subscribe<nav_msgs::Odometry>(
    param.fcu_odom_topic, 10,
    bind(&MavRosConnect::FcuOdomCallback, mavros, _1));

  tgt_pose_pub =
    nh_->advertise<mavros_msgs::PositionTarget>(param.pos_tgt_topic, 10);

  att_pub =
    nh_->advertise<mavros_msgs::AttitudeTarget>(param.att_tgt_topic, 10);

  set_mode_client =
    nh_->serviceClient<mavros_msgs::SetMode>(param.set_mode_service);
  arming_client =
    nh_->serviceClient<mavros_msgs::CommandBool>(param.arm_service);

  // 加载安全边界参数
  nh_->param<bool>("safety/enabled", safety_boundary_.enabled, false);
  nh_->param<double>("safety/x_min", safety_boundary_.x_min, -10.0);
  nh_->param<double>("safety/x_max", safety_boundary_.x_max, 10.0);
  nh_->param<double>("safety/y_min", safety_boundary_.y_min, -10.0);
  nh_->param<double>("safety/y_max", safety_boundary_.y_max, 10.0);
  nh_->param<double>("safety/z_min", safety_boundary_.z_min, 0.0);
  nh_->param<double>("safety/z_max", safety_boundary_.z_max, 5.0);
  nh_->param<double>("safety/recovery_margin", safety_boundary_.recovery_margin, 0.20);
  nh_->param<double>("safety/recovery_confirm_time", safety_boundary_.recovery_confirm_time, 0.50);
  safety_boundary_.recovery_margin = std::max(0.0, safety_boundary_.recovery_margin);
  safety_boundary_.recovery_confirm_time = std::max(0.0, safety_boundary_.recovery_confirm_time);

  if (safety_boundary_.enabled) {
    ROS_INFO("Safety boundary enabled: X[%.1f, %.1f] Y[%.1f, %.1f] Z[%.1f, %.1f]",
             safety_boundary_.x_min, safety_boundary_.x_max,
             safety_boundary_.y_min, safety_boundary_.y_max,
             safety_boundary_.z_min, safety_boundary_.z_max);
  }

  // 初始化定时发布 (50Hz)
  has_init_cmd = false;
  safety_state_ = SafetyState::NORMAL;
  recovery_enter_time_ = ros::Time(0);
  recovery_inside_since_ = ros::Time(0);
  node_start_time_ = ros::Time::now();
  cmd_timer = nh_->createTimer(ros::Duration(0.02), &MavRosConnect::cmdPublishLoop, this);
}

const MavRosConnect::Param *MavRosConnect::getParam()
{
  return &param;
}

const nav_msgs::Odometry *MavRosConnect::getFcuOdom()
{
  return &fcu_odom;
}


const mavros_msgs::State *MavRosConnect::getFcuState()
{
  return &fcu_state;
}

ros::ServiceClient *MavRosConnect::getSetModeClient()
{
  return &set_mode_client;
}

ros::ServiceClient *MavRosConnect::getArmClient()
{
  return &arming_client;
}

ros::Publisher *MavRosConnect::getPosTgtPublisher()
{
  return &tgt_pose_pub;
}

ros::Publisher *MavRosConnect::getAttTgtPublisher()
{
  return &att_pub;
}



std::shared_ptr<ros::NodeHandle> MavRosConnect::getROSHandle()
{
  return nh_;
}

std::mutex &MavRosConnect::GetPoseMtx()
 {
    return pose_mtx;
 }
void MavRosConnect::FcuStateCallback(const mavros_msgs::State::ConstPtr &msg)
{
  std::lock_guard<std::mutex> lock(pose_mtx);
  if (!fcu_state_received_) {
    fcu_state_received_ = true;
    ROS_INFO("[MavRosConnect] Flight controller state connected (mavros/state)");
  }
  fcu_state = *msg;
}

void MavRosConnect::FcuOdomCallback(const nav_msgs::Odometry::ConstPtr &msg)
{
  if (!fcu_odom_received_) {
    fcu_odom_received_ = true;
    ROS_INFO("[MavRosConnect] Drone localization connected (odom)");
  }
  fcu_odom = *msg;
}

void MavRosConnect::updateCommand(const mavros_msgs::PositionTarget &cmd)
{
    std::lock_guard<std::mutex> lock(cmd_mtx);
    current_cmd = cmd;
    has_init_cmd = true;
}

void MavRosConnect::cmdPublishLoop(const ros::TimerEvent &event)
{
    // 跟踪启动后的延迟，避免刚启动时立即警告
    constexpr double STARTUP_DELAY_SEC = 2.0;
    bool is_startup_period = (ros::Time::now() - node_start_time_).toSec() < STARTUP_DELAY_SEC;

    // 检查是否接收到飞控状态信息
    if (!fcu_state_received_ || !fcu_odom_received_) {
        if (!is_startup_period) {
            if (!fcu_state_received_) ROS_WARN_THROTTLE(2.0, "[MavRosConnect] Waiting for FCU state...");
            if (!fcu_odom_received_) ROS_WARN_THROTTLE(2.0, "[MavRosConnect] Waiting for FCU odom...");
        }
        return;
    }

    // 提前检查是否已初始化指令 (用户需求)
    if (!has_init_cmd) {
        return;
    }

    ros::Time now = ros::Time::now();

    // 安全恢复状态机。恢复命令只在最终发布层覆盖输出，不写入 current_cmd。
    if (safety_boundary_.enabled) {
        if (safety_state_ == SafetyState::NORMAL && !isWithinBoundary()) {
            recovery_pos_ = fcu_odom.pose.pose.position;
            recovery_pos_.x = std::min(std::max(recovery_pos_.x,
                                                 safety_boundary_.x_min + safety_boundary_.recovery_margin),
                                       safety_boundary_.x_max - safety_boundary_.recovery_margin);
            recovery_pos_.y = std::min(std::max(recovery_pos_.y,
                                                 safety_boundary_.y_min + safety_boundary_.recovery_margin),
                                       safety_boundary_.y_max - safety_boundary_.recovery_margin);
            recovery_pos_.z = std::min(std::max(recovery_pos_.z,
                                                 safety_boundary_.z_min + safety_boundary_.recovery_margin),
                                       safety_boundary_.z_max - safety_boundary_.recovery_margin);

            tf2::Quaternion q;
            tf2::fromMsg(fcu_odom.pose.pose.orientation, q);
            double r, p, y;
            tf2::Matrix3x3(q).getRPY(r, p, y);
            recovery_yaw_ = y;
            recovery_enter_time_ = now;
            recovery_inside_since_ = ros::Time(0);
            safety_state_ = SafetyState::RECOVERING;

            ROS_ERROR("[SafetyRecovery] ENTER DRONE OUT OF BOUNDARY");
            ROS_ERROR("[SafetyRecovery] current position = (%.2f, %.2f, %.2f)",
                      fcu_odom.pose.pose.position.x,
                      fcu_odom.pose.pose.position.y,
                      fcu_odom.pose.pose.position.z);
            ROS_ERROR("[SafetyRecovery] recovery target = (%.2f, %.2f, %.2f)",
                      recovery_pos_.x, recovery_pos_.y, recovery_pos_.z);
        }

        if (safety_state_ == SafetyState::RECOVERING) {
            if (isWithinInnerBoundary()) {
                if (recovery_inside_since_.isZero()) {
                    recovery_inside_since_ = now;
                    ROS_INFO("[SafetyRecovery] INSIDE INNER BOUNDARY confirmation started");
                } else if ((now - recovery_inside_since_).toSec() >=
                           safety_boundary_.recovery_confirm_time) {
                    const double recovery_duration = (now - recovery_enter_time_).toSec();
                    safety_state_ = SafetyState::NORMAL;
                    recovery_inside_since_ = ros::Time(0);
                    ROS_INFO("[SafetyRecovery] COMPLETE recovery duration = %.3f s; "
                             "latest command control resumed; Drone returned to safe area.",
                             recovery_duration);
                }
            } else if (!recovery_inside_since_.isZero()) {
                recovery_inside_since_ = ros::Time(0);
                ROS_WARN("[SafetyRecovery] confirmation reset");
            }
        }
    } else if (safety_state_ == SafetyState::RECOVERING) {
        safety_state_ = SafetyState::NORMAL;
        recovery_inside_since_ = ros::Time(0);
    }

    // 统一发布：RECOVERING 时只替换本次发布值，current_cmd 始终保留上层最新命令。
    mavros_msgs::PositionTarget output_cmd;
    std::lock_guard<std::mutex> lock(cmd_mtx);
    output_cmd = current_cmd;
    if (safety_state_ == SafetyState::RECOVERING) {
        output_cmd = makeRecoveryCommand(now);
    }
    output_cmd.header.stamp = now;
    tgt_pose_pub.publish(output_cmd);
}

bool MavRosConnect::isWithinBoundary() const
{
    // odom 和安全参数都是 ENU，直接比较
    double x = fcu_odom.pose.pose.position.x;
    double y = fcu_odom.pose.pose.position.y;
    double z = fcu_odom.pose.pose.position.z;
    return (x >= safety_boundary_.x_min && x <= safety_boundary_.x_max &&
            y >= safety_boundary_.y_min && y <= safety_boundary_.y_max &&
            z >= safety_boundary_.z_min && z <= safety_boundary_.z_max);
}

bool MavRosConnect::isWithinInnerBoundary() const
{
    double x = fcu_odom.pose.pose.position.x;
    double y = fcu_odom.pose.pose.position.y;
    double z = fcu_odom.pose.pose.position.z;
    const double margin = safety_boundary_.recovery_margin;
    return (x >= safety_boundary_.x_min + margin && x <= safety_boundary_.x_max - margin &&
            y >= safety_boundary_.y_min + margin && y <= safety_boundary_.y_max - margin &&
            z >= safety_boundary_.z_min + margin && z <= safety_boundary_.z_max - margin);
}

mavros_msgs::PositionTarget MavRosConnect::makeRecoveryCommand(const ros::Time &stamp) const
{
    mavros_msgs::PositionTarget recovery_cmd;
    recovery_cmd.header.stamp = stamp;
    recovery_cmd.header.frame_id = "safety_recovery";
    recovery_cmd.coordinate_frame = mavros_msgs::PositionTarget::FRAME_LOCAL_NED;
    recovery_cmd.type_mask = mavros_msgs::PositionTarget::IGNORE_VX |
                             mavros_msgs::PositionTarget::IGNORE_VY |
                             mavros_msgs::PositionTarget::IGNORE_VZ |
                             mavros_msgs::PositionTarget::IGNORE_YAW_RATE |
                             mavros_msgs::PositionTarget::IGNORE_AFX |
                             mavros_msgs::PositionTarget::IGNORE_AFY |
                             mavros_msgs::PositionTarget::IGNORE_AFZ |
                             mavros_msgs::PositionTarget::FORCE;
    // ENU -> NED conversion, matching publishPosition().
    recovery_cmd.position.x = -recovery_pos_.y;
    recovery_cmd.position.y = recovery_pos_.x;
    recovery_cmd.position.z = recovery_pos_.z;
    recovery_cmd.yaw = recovery_yaw_ + M_PI / 2.0;
    return recovery_cmd;
}

MavRosConnect::MavRosConnect(std::shared_ptr<ros::NodeHandle> nh)
{
  nh_ = nh;
}
