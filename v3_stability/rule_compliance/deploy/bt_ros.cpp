/******************************************************************************
 * @file       bt_ros.cpp
 * @brief      行为树 ROS 主节点 - 加载和执行任务行为树
 * 
 * @details    支持两种运行模式：
 *             - static: 从 XML 文件加载并执行（原有行为）
 *             - llm:    监听 ROS Topic，接收 LLM 指令动态构建行为树执行
 * 
 * @author     郭定<1604289397@qq.com>
 * @date       2026-01-06
 *****************************************************************************/
#include <ros/ros.h>
#include <utils/common.hpp>
#include <behaviortree_cpp/xml_parsing.h>
#include <boost/stacktrace.hpp>
#include <std_msgs/String.h>

#include <csignal>
#include <filesystem>
#include <fstream>
#include <vector>
#include <string>
#include <sstream>
#include <mutex>
#include <condition_variable>
#include <atomic>
#include <chrono>
#include <thread>
#include <iomanip>
#include <random>
#include <set>
#include <cmath>
#include <regex>
#include <unordered_map>
#include <mavros_msgs/SetMode.h>
#include <tf2/LinearMath/Quaternion.h>
#include <tf2_geometry_msgs/tf2_geometry_msgs.h>

#include "sequence_session.hpp"
#include "nlohmann_json.hpp"
#include "mavros_cnt.h"
#include "nodes/action/takeoff.h"
#include "nodes/action/land.h"

namespace fs = std::filesystem;
using namespace BT;
using json = nlohmann::json;

//==============================================================================
// 常量定义
//==============================================================================
namespace {
    constexpr int ASYNC_SPINNER_THREADS = 2;
    const std::string LIB_PREFIX = "lib";
    const std::string SO_EXTENSION = ".so";
}

//==============================================================================
// 信号处理
//==============================================================================

/**
 * @brief 信号处理函数 - 捕获崩溃信号并打印堆栈跟踪
 */
void signalHandler(int signum) {
    std::cerr << "\n[FATAL] Received signal " << signum << std::endl;
    std::cerr << "Stack trace:\n" << boost::stacktrace::stacktrace();
    std::exit(signum);
}

/**
 * @brief 注册信号处理器
 */
void registerSignalHandlers() {
    std::signal(SIGSEGV, signalHandler);
    std::signal(SIGABRT, signalHandler);
}

//==============================================================================
// 插件加载
//==============================================================================

/**
 * @brief 从 devel/lib 目录扫描并加载行为树插件 (.so 文件)
 * @return 插件文件的完整路径列表
 */
std::vector<std::string> loadPluginLibraries() {
    std::vector<std::string> lib_files;
    
    const char* cmake_prefix_path = std::getenv("CMAKE_PREFIX_PATH");
    if (!cmake_prefix_path) {
        ROS_ERROR("CMAKE_PREFIX_PATH environment variable not set!");
        return lib_files;
    }

    std::string prefix_path_str(cmake_prefix_path);
    size_t devel_pos = prefix_path_str.find("/devel");
    
    if (devel_pos == std::string::npos) {
        ROS_ERROR("Failed to find 'devel' in CMAKE_PREFIX_PATH: %s", prefix_path_str.c_str());
        return lib_files;
    }

    std::string devel_lib_path = prefix_path_str.substr(0, devel_pos + 6) + "/lib";
    
    try {
        for (const auto& entry : fs::directory_iterator(devel_lib_path)) {
            if (!entry.is_regular_file() || entry.path().extension() != SO_EXTENSION) {
                continue;
            }
            
            std::string filename = entry.path().filename().string();
            // 只加载非标准库文件（不以 "lib" 开头的 .so 文件）
            if (filename.substr(0, LIB_PREFIX.size()) != LIB_PREFIX) {
                lib_files.push_back(entry.path().string());
                ROS_DEBUG("Found plugin: %s", filename.c_str());
            }
        }
        ROS_INFO("Loaded %zu plugin(s) from: %s", lib_files.size(), devel_lib_path.c_str());
    } catch (const fs::filesystem_error& e) {
        ROS_ERROR("Filesystem error while loading plugins: %s", e.what());
    }

    if (lib_files.empty()) {
        ROS_WARN("No behavior tree plugins found in %s", devel_lib_path.c_str());
    }

    return lib_files;
}

/**
 * @brief 注册所有插件到行为树工厂
 */
void registerPlugins(BehaviorTreeFactory& factory, const std::vector<std::string>& plugin_files) {
    for (const auto& plugin_path : plugin_files) {
        try {
            factory.registerFromPlugin(plugin_path);
            ROS_DEBUG("Registered plugin: %s", plugin_path.c_str());
        } catch (const std::exception& e) {
            ROS_ERROR("Failed to register plugin %s: %s", plugin_path.c_str(), e.what());
        }
    }
}

//==============================================================================
// 配置管理
//==============================================================================

/**
 * @brief 行为树配置参数
 */
struct BehaviorTreeConfig {
    std::string tree_config_path;
    bool is_debug;
    bool generate_xml;
    std::string xml_output_file;
    std::string mode;  // "static" or "llm"
};

/**
 * @brief 从 ROS 参数服务器加载配置
 */
BehaviorTreeConfig loadConfiguration(ros::NodeHandle& nh_private) {
    BehaviorTreeConfig config;
    
    nh_private.param<std::string>("config_path", config.tree_config_path,
                                   "/home/zy/ws/src/mission_pkg/config/hitballon.xml");
    nh_private.param<bool>("is_debug", config.is_debug, false);
    nh_private.param<bool>("is_gen_xml", config.generate_xml, false);
    nh_private.param<std::string>("xml_file", config.xml_output_file, "cfg.xml");
    nh_private.param<std::string>("mode", config.mode, "static");
    
    ROS_INFO("Behavior Tree Config Path: %s", config.tree_config_path.c_str());
    ROS_INFO("Mode: %s", config.mode.c_str());
    
    return config;
}

//==============================================================================
// XML 生成
//==============================================================================

/**
 * @brief 生成行为树节点模型 XML 文件（用于调试和文档）
 */
bool generateNodeModelXML(const BehaviorTreeFactory& factory, const std::string& output_file) {
    try {
        auto xml_model = writeTreeNodesModelXML(factory, false);
        
        std::ofstream file(output_file);
        if (!file.is_open()) {
            ROS_ERROR("Failed to open file for writing: %s", output_file.c_str());
            return false;
        }
        
        file << xml_model;
        file.close();
        
        ROS_INFO("Successfully generated XML model: %s", output_file.c_str());
        return true;
        
    } catch (const std::exception& e) {
        ROS_ERROR("Failed to generate XML model: %s", e.what());
        return false;
    }
}

//==============================================================================
// LLM 指令 → 行为树 XML 动态构建
//==============================================================================

/**
 * @brief 将单条 LLM 指令转换为行为树 XML 片段
 * 
 * 支持的指令格式：
 *   takeoff
 *   cross_frame
 *   detect_aruco
 *   return_cross_frame
 *   hit_balloon:区域:颜色       (例: hit_balloon:A:red)
 *   land
 */
std::string commandToXmlNode(const std::string& command, bool offline = false) {
    // 去除前后空白
    std::string cmd = command;
    cmd.erase(0, cmd.find_first_not_of(" \t\r\n"));
    cmd.erase(cmd.find_last_not_of(" \t\r\n") + 1);
    
    if (cmd.empty()) throw std::invalid_argument("empty command");

    if (cmd != "takeoff" && cmd != "cross_frame" && cmd != "detect_aruco" &&
        cmd != "return_cross_frame" && cmd != "land" && cmd != "emergency_land" &&
        cmd != "hit_balloon:red" && cmd != "hit_balloon:purple" && cmd != "hit_balloon:blue")
        throw std::invalid_argument("invalid command: " + cmd);

    // 读取参数的辅助 lambda
    std::unique_ptr<ros::NodeHandle> nh;
    if (!offline) nh = std::make_unique<ros::NodeHandle>();
    auto getStr = [&](const std::string& key, const std::string& def) -> std::string {
        std::string val;
        if (!nh || !nh->getParam(key, val)) val = def;
        return val;
    };
    auto getDbl = [&](const std::string& key, double def) -> double {
        double val;
        if (!nh || !nh->getParam(key, val)) val = def;
        return val;
    };

    // ---- takeoff ----
    if (cmd == "takeoff") {
        std::string goal = getStr("takeoff/goal", "0.0;0.0;1.0");
        double yaw_val = 0;
        bool has_yaw = nh && nh->getParam("takeoff/yaw", yaw_val);
        if (has_yaw) {
            return "      <Takeoff goal=\"" + goal + "\" yaw=\"" + std::to_string(yaw_val) + "\"/>\n";
        }
        return "      <Takeoff goal=\"" + goal + "\"/>\n";
    }
    
    // ---- cross_frame: 识别方框 + 穿越 ----
    if (cmd == "cross_frame") {
        std::string observe   = getStr("cross_frame/observe_pos",   "0.0;-1.0;1.0");
        std::string stable_pos_threshold =
            std::to_string(getDbl("optimization/position_threshold", 0.15));
        std::string stable_vel_threshold =
            std::to_string(getDbl("optimization/velocity_threshold", 0.08));
        std::string stable_confirm_time =
            std::to_string(getDbl("optimization/stable_confirm_time", 0.50));
        std::string stable_timeout =
            std::to_string(getDbl("optimization/settle_timeout",
                                  getDbl("cross_frame/observe_delay_ms", 2000) / 1000.0));
        std::string obj_w     = std::to_string(getDbl("cross_frame/object_width",  1.25));
        std::string obj_h     = std::to_string(getDbl("cross_frame/object_height", 1.25));
        std::string occ_dir   = getStr("cross_frame/occlusion_direction", "right");
        std::string exp_pos   = getStr("cross_frame/expected_pos",  "0.4;3.25;1.0");
        std::string z_tol     = std::to_string(getDbl("cross_frame/z_tolerance", 0.5));
        std::string filter_w  = std::to_string((int)getDbl("cross_frame/filter_window_size", 20));
        std::string offset_z  = std::to_string(getDbl("cross_frame/offset_z", 1.0));
        
        return 
            "      <!-- 移动到观察位置 -->\n"
            "      <GoTo goal=\"" + observe + "\"/>\n"
            "      <!-- 等待位置和速度稳定；超时保持原有 2 s 上限 -->\n"
            "      <WaitForStablePosition goal=\"" + observe + "\" "
            "position_threshold=\"" + stable_pos_threshold + "\" "
            "velocity_threshold=\"" + stable_vel_threshold + "\" "
            "stable_confirm_time=\"" + stable_confirm_time + "\" "
            "timeout=\"" + stable_timeout + "\"/>\n"
            "      <!-- 识别方框位置 -->\n"
            "      <TargetLocator object_name=\"square_frame\" object_width=\"" + obj_w + "\" object_height=\"" + obj_h + "\" "
            "occlusion_direction=\"" + occ_dir + "\" expected_pos=\"" + exp_pos + "\" "
            "xy_tolerance=\"1.0\" z_tolerance=\"" + z_tol + "\" "
            "confidence_threshold=\"0.7\" "
            "position_3d=\"{frame_center}\" filter_window_size=\"" + filter_w + "\"/>\n"
            "      <!-- 规划穿过方框 -->\n"
            "      <PlanningControl goal=\"{frame_center}\" offset_z=\"" + offset_z + "\" final_position=\"{planning_end_pos}\"/>\n";
    }
    
    // ---- detect_aruco: 飞到二维码上方识别 ----
    if (cmd == "detect_aruco") {
        std::string hover = getStr("aruco/hover_pos", "-1.0;4.0;1.8");
        return
            "      <GoTo goal=\"" + hover + "\"/>\n"
            "      <Parallel success_count=\"2\" failure_count=\"1\">\n"
            "        <GoTo goal=\"" + hover + "\"/>\n"
            "        <ArucoDetector aruco_id=\"{detected_aruco_id}\"/>\n"
            "      </Parallel>\n";
    }
    
    // ---- return_cross_frame: 返回并反向穿越方框 ----
    if (cmd == "return_cross_frame") {
        std::string turn_pos     = getStr("return_cross_frame/turn_pos",   "-1.0;4.0;1.8");
        double      turn_yaw     = getDbl("return_cross_frame/turn_yaw",   3.14159);
        std::string body_fwd     = getStr("return_cross_frame/body_forward", "0.5;0.0;0.0");
        double      exit_yaw     = getDbl("return_cross_frame/exit_yaw",   0.0);
        
        return
            "      <!-- 旋转180度 -->\n"
            "      <GoTo goal=\"" + turn_pos + "\" yaw=\"" + std::to_string(turn_yaw) + "\"/>\n"
            "      <!-- 返回规划终点 -->\n"
            "      <GoTo goal=\"{planning_end_pos}\" continue_previous=\"true\"/>\n"
            "      <!-- 反向穿越方框 -->\n"
            "      <PlanningControl goal=\"{frame_center}\"/>\n"
            "      <!-- 机体系前进 -->\n"
            "      <GoTo goal=\"" + body_fwd + "\" frame=\"1\"/>\n"
            "      <!-- 掉头朝向气球区域 -->\n"
            "      <GoTo yaw=\"" + std::to_string(exit_yaw) + "\" continue_previous=\"true\"/>\n";
    }
    
    // ---- hit_balloon:颜色 ----
    if (cmd.rfind("hit_balloon", 0) == 0) {
        std::string color = cmd.substr(std::string("hit_balloon:").size());
        
        std::string zone;
        if (offline) zone = color == "red" ? "A" : (color == "purple" ? "B" : "C");
        else if (!nh->getParam("balloon_color_" + color, zone) || (zone != "A" && zone != "B" && zone != "C"))
            throw std::runtime_error("MISSING_BALLOON_COLOR_MAPPING:" + color);
        
        std::string param_prefix = "balloon_zone_" + zone;
        if (!offline && (!nh->hasParam(param_prefix + "/approach_pos") ||
            !nh->hasParam(param_prefix + "/goal") || (zone != "A" && !nh->hasParam(param_prefix + "/yaw"))))
            throw std::runtime_error("MISSING_BALLOON_ZONE_PARAMETERS:" + zone);
        std::string approach_pos = getStr(param_prefix + "/approach_pos", "5.3;1.0;0.7");
        std::string goto_pos = getStr(param_prefix + "/goal", "0.0;-0.8;0.5");
        double yaw_val = getDbl(param_prefix + "/yaw", -1.570796);
        std::string yaw = std::to_string(yaw_val);
        std::string yaw_attribute = zone == "A" ? "" : " yaw=\"" + yaw + "\"";
        std::string balloon_name = color + "_balloon";
        
        // VisualServo 参数（从参数服务器读取，与手调 XML 一致）
        std::string vs_k_p_yaw  = std::to_string(getDbl("visual_servo/k_p_yaw_rate", 0.1));
        std::string vs_k_d_yaw  = std::to_string(getDbl("visual_servo/k_d_yaw_rate", 0.008));
        std::string vs_k_p_vz   = std::to_string(getDbl("visual_servo/k_p_vz", 0.01));
        std::string vs_k_d_vz   = std::to_string(getDbl("visual_servo/k_d_vz", 0.006));
        std::string vs_area_th  = std::to_string(getDbl("visual_servo/approach_area_threshold", 0.08));
        std::string vs_fwd_vel  = std::to_string(getDbl("visual_servo/forward_velocity", 1.0));
        std::string vs_sprint_v = std::to_string(getDbl("visual_servo/sprint_velocity", 1.5));
        std::string vs_sprint_t = std::to_string(getDbl("visual_servo/sprint_time", 1.2));
        
        ROS_INFO("Hit balloon: color=%s -> zone=%s, approach=%s, goto=%s, yaw=%s, target=%s", 
                 color.c_str(), zone.c_str(), approach_pos.c_str(), goto_pos.c_str(),
                 zone == "A" ? "preserved" : yaw.c_str(), balloon_name.c_str());
        
        return
            "      <!-- 规划飞到气球打击区域" + zone + " -->\n"
            "      <PlanningControl goal=\"" + approach_pos + "\"/>\n"
            "      <!-- 转向朝向" + zone + "区气球(" + color + ") -->\n"
            "      <GoTo goal=\"" + goto_pos + "\"" + yaw_attribute + "/>\n"
            "      <!-- 跟踪并撞击气球 -->\n"
            "        <Timeout msec=\"50000\">\n"
            "          <Parallel success_count=\"1\" failure_count=\"1\">\n"
            "            <TargetTracker object_name=\"" + balloon_name + "\" "
            "confidence_threshold=\"0.8\" filter_window_size=\"1\" pixel_target=\"{balloon_pixel}\"/>\n"
            "            <VisualServo pixel_target=\"{balloon_pixel}\" target_color=\"" + color + "\" "
            "k_p_yaw_rate=\"" + vs_k_p_yaw + "\" k_d_yaw_rate=\"" + vs_k_d_yaw + "\" "
            "k_p_vz=\"" + vs_k_p_vz + "\" k_d_vz=\"" + vs_k_d_vz + "\" "
            "approach_area_threshold=\"" + vs_area_th + "\" "
            "forward_velocity=\"" + vs_fwd_vel + "\" sprint_velocity=\"" + vs_sprint_v + "\" sprint_time=\"" + vs_sprint_t + "\" yaw_feedforward_gain=\"0.0\"/>\n"
            "          </Parallel>\n"
            "        </Timeout>\n";
    }
    
    // ---- land ----
    if (cmd == "land") {
        return mission_sequence::landXml(getStr, getDbl);
    }
    if (cmd == "emergency_land") return "      <Land/>\n";
    
    throw std::logic_error("unhandled validated command");
}

/**
 * @brief 将 LLM 指令列表构建为完整的行为树 XML
 */
std::string buildXmlFromCommands(const std::vector<std::string>& commands, bool offline = false) {
    std::string xml = R"(<?xml version="1.0" encoding="UTF-8"?>
<root BTCPP_format="4" main_tree_to_execute="LLMTask">
  <BehaviorTree ID="LLMTask">
    <Sequence name="LLMSequence">
)";
    for (const auto& cmd : commands) {
        std::string node_xml = commandToXmlNode(cmd, offline);
        if (!node_xml.empty()) {
            xml += node_xml;
        }
    }
    xml += R"(    </Sequence>
  </BehaviorTree>
</root>)";
    return xml;
}

bool validateSequentialTrees(BehaviorTreeFactory& factory, bool offline = false) {
    bool valid = true;
    for (const std::string command : {"takeoff", "cross_frame", "detect_aruco",
             "return_cross_frame", "hit_balloon:red", "hit_balloon:purple",
             "hit_balloon:blue", "land", "emergency_land"}) {
        try {
            const auto xml = buildXmlFromCommands({command}, offline);
            if (offline) {
                std::unordered_map<std::string, BT::NodeType> registered;
                for (const auto& manifest : factory.manifests())
                    registered.emplace(manifest.first, manifest.second.type);
                BT::VerifyXML(xml, registered);
                const std::regex node_pattern(R"(<(\w+)\s+([^<>]*?)/?>)");
                const std::regex attribute_pattern(R"attr((\w+)\s*=\s*"[^"]*")attr");
                for (auto node = std::sregex_iterator(xml.begin(), xml.end(), node_pattern);
                     node != std::sregex_iterator(); ++node) {
                    const auto manifest = factory.manifests().find((*node)[1].str());
                    if (manifest == factory.manifests().end()) continue;
                    const auto attributes = (*node)[2].str();
                    for (auto attr = std::sregex_iterator(attributes.begin(), attributes.end(), attribute_pattern);
                         attr != std::sregex_iterator(); ++attr) {
                        const auto port = (*attr)[1].str();
                        if (port != "name" && port != "ID" && !manifest->second.ports.count(port))
                            throw std::runtime_error("Unknown port " + port + " on " + manifest->first);
                    }
                }
            } else {
                auto board = BT::Blackboard::create();
                board->set("frame_center", Position3D{});
                board->set("planning_end_pos", Position3D{});
                // Construct but never tick: validate blackboard wiring before flight.
                auto tree = factory.createTreeFromText(xml, board);
            }
            ROS_INFO("Sequential tree validated without ticking: %s", command.c_str());
        } catch (const std::exception& e) {
            ROS_ERROR("Sequential tree preflight failed [%s]: %s", command.c_str(), e.what());
            valid = false;
        }
    }
    return valid;
}

static BehaviorTreeFactory* g_factory_ptr = nullptr;

//==============================================================================
// Sequential command session
//==============================================================================

static std::mutex g_session_mutex;
static std::mutex g_worker_mutex;
static std::thread g_worker;
static std::thread g_idle_watchdog;
static std::mutex g_idle_mutex;
static std::condition_variable g_idle_cv;
static bool g_idle_pending = false;
static bool g_idle_shutdown = false;
static bool g_idle_land_requested = false;
static bool g_last_known_armed = false;
static std::unique_ptr<mission_sequence::Session> g_session;
static BT::Blackboard::Ptr g_blackboard;
static std::shared_ptr<MavRosConnect> g_mavros;
static ros::Publisher g_status_pub;
static ros::Publisher g_ready_pub;
static std::atomic<bool> g_sequential_abort{false};
static double g_command_timeout_s = 120.0;
static std::mutex g_telemetry_mutex;
static mavros_msgs::State g_fcu_state;
static nav_msgs::Odometry g_fcu_odom;
static std::chrono::steady_clock::time_point g_state_received, g_odom_received;
static ros::ServiceClient g_set_mode;
static std::set<std::pair<std::string, std::string>> g_pending_aborts;

void stateSnapshotCallback(const mavros_msgs::State::ConstPtr& msg) {
    std::lock_guard<std::mutex> lock(g_telemetry_mutex);
    g_fcu_state = *msg;
    g_state_received = std::chrono::steady_clock::now();
}

void odomSnapshotCallback(const nav_msgs::Odometry::ConstPtr& msg) {
    std::lock_guard<std::mutex> lock(g_telemetry_mutex);
    g_fcu_odom = *msg;
    g_odom_received = std::chrono::steady_clock::now();
}

struct Telemetry {
    mavros_msgs::State state;
    nav_msgs::Odometry odom;
    bool state_fresh, odom_fresh;
    mission_sequence::TelemetryHealth health;
    std::string diagnostics() const {
        return health.diagnostics(state.connected, state.armed, state.mode);
    }
};

Telemetry snapshot() {
    std::lock_guard<std::mutex> lock(g_telemetry_mutex);
    const auto now = std::chrono::steady_clock::now();
    const auto ros_now = ros::Time::now();
    mission_sequence::TelemetryHealth health;
    health.state_received = g_state_received != std::chrono::steady_clock::time_point{};
    health.odom_received = g_odom_received != std::chrono::steady_clock::time_point{};
    health.state_stamp_valid = !g_fcu_state.header.stamp.isZero();
    health.odom_stamp_valid = !g_fcu_odom.header.stamp.isZero();
    health.state_receive_age = std::chrono::duration<double>(now - g_state_received).count();
    health.odom_receive_age = std::chrono::duration<double>(now - g_odom_received).count();
    health.state_source_age = (ros_now - g_fcu_state.header.stamp).toSec();
    health.odom_source_age = (ros_now - g_fcu_odom.header.stamp).toSec();
    const auto& position = g_fcu_odom.pose.pose.position;
    const auto& q = g_fcu_odom.pose.pose.orientation;
    health.position_finite = std::isfinite(position.x) && std::isfinite(position.y) && std::isfinite(position.z);
    health.quaternion_finite = std::isfinite(q.x) && std::isfinite(q.y) && std::isfinite(q.z) && std::isfinite(q.w);
    health.quaternion_norm_squared = q.x*q.x + q.y*q.y + q.z*q.z + q.w*q.w;
    return {g_fcu_state, g_fcu_odom, health.stateFresh(), health.odomFresh(), health};
}

bool requestAutoLand() {
    mavros_msgs::PositionTarget stop;
    stop.coordinate_frame = mavros_msgs::PositionTarget::FRAME_LOCAL_NED;
    stop.type_mask = mavros_msgs::PositionTarget::IGNORE_PX | mavros_msgs::PositionTarget::IGNORE_PY |
                     mavros_msgs::PositionTarget::IGNORE_PZ | mavros_msgs::PositionTarget::IGNORE_AFX |
                     mavros_msgs::PositionTarget::IGNORE_AFY | mavros_msgs::PositionTarget::IGNORE_AFZ |
                     mavros_msgs::PositionTarget::IGNORE_YAW | mavros_msgs::PositionTarget::FORCE;
    g_mavros->updateCommand(stop);
    mavros_msgs::SetMode mode;
    mode.request.custom_mode = "AUTO.LAND";
    try { return g_set_mode.call(mode) && mode.response.mode_sent; }
    catch (const std::exception& e) {
        ROS_ERROR("AUTO.LAND service failed: %s", e.what());
        return false;
    }
}

std::string makeEpoch() {
    std::random_device device;
    std::ostringstream out;
    out << std::hex << std::setfill('0');
    for (int i = 0; i < 4; ++i) out << std::setw(8) << device();
    return out.str();
}

void publishStatus(const std::string& session, const std::string& id,
                   const std::string& command, const std::string& status,
                   const std::string& reason = "") {
    json message = {{"protocol", 1}, {"server_epoch", g_session->epoch()},
                    {"session_id", session}, {"request_id", id},
                    {"command", command}, {"status", status}};
    if (!reason.empty()) message["reason"] = reason;
    std_msgs::String output;
    output.data = message.dump();
    g_status_pub.publish(output);
}

void publishReady(const ros::TimerEvent&) {
    bool request_idle_land = false;
    json message;
    {
        std::lock_guard<std::mutex> lock(g_session_mutex);
        const auto telemetry = snapshot();
        if (telemetry.state_fresh && telemetry.state.connected) {
            g_last_known_armed = telemetry.state.armed;
            if (!g_last_known_armed) g_idle_land_requested = false;
        }
        if (mission_sequence::idleRecoveryNeeded(g_session->busy(), g_last_known_armed,
                telemetry.state_fresh, telemetry.state.connected, telemetry.odom_fresh,
                telemetry.state.mode)) {
            g_session->requireRecovery();
            if (!g_idle_land_requested) {
                g_idle_land_requested = true;
                request_idle_land = true;
                ROS_ERROR("Idle airborne telemetry lost; requesting AUTO.LAND: %s",
                          telemetry.diagnostics().c_str());
            }
        }
        message = {{"protocol", 1}, {"server_epoch", g_session->epoch()},
                   {"session_id", g_session->session()}, {"status", "READY"},
                   {"state", g_session->busy() ? "BUSY" :
                       (g_session->recoveryRequired() ? "RECOVERY_REQUIRED" : "IDLE")},
                   {"state_fresh", telemetry.state_fresh},
                   {"odom_fresh", telemetry.odom_fresh},
                   {"connected", telemetry.state.connected},
                   {"armed", telemetry.state.armed},
                   {"mode", telemetry.state.mode},
                   {"telemetry_healthy", mission_sequence::telemetryHealthy(
                       telemetry.state_fresh, telemetry.state.connected, telemetry.state.armed,
                       telemetry.odom_fresh, false, false, false, telemetry.state.mode)},
                   {"active_request_id", g_session->activeId()},
                   {"active_command", g_session->activeCommand()},
                   {"last_request_id", g_session->lastId()},
                   {"last_command", g_session->lastCommand()},
                   {"last_status", g_session->lastStatus()},
                   {"last_reason", g_session->lastReason()}};
    }
    std_msgs::String output;
    output.data = message.dump();
    g_ready_pub.publish(output);
    if (request_idle_land) {
        {
            std::lock_guard<std::mutex> lock(g_idle_mutex);
            g_idle_pending = true;
        }
        g_idle_cv.notify_one();
    }
}

void idleAutoLandWorker() {
    for (;;) {
        {
            std::unique_lock<std::mutex> lock(g_idle_mutex);
            g_idle_cv.wait(lock, [] { return g_idle_pending || g_idle_shutdown; });
            if (g_idle_shutdown) return;
            g_idle_pending = false;
        }
        std::lock_guard<std::mutex> worker_lock(g_worker_mutex);
        bool still_idle;
        {
            std::lock_guard<std::mutex> lock(g_session_mutex);
            still_idle = !g_session->busy() && g_last_known_armed && g_idle_land_requested;
        }
        if (still_idle && !requestAutoLand())
            ROS_ERROR("Idle watchdog AUTO.LAND request failed");
    }
}

void holdCurrentPosition() {
    const auto telemetry = snapshot();
    if (!telemetry.odom_fresh)
        throw std::runtime_error("NO_FRESH_ODOMETRY_FOR_HOLD; " + telemetry.diagnostics());
    mavros_msgs::PositionTarget target;
    {
        const auto& position = telemetry.odom.pose.pose.position;
        target.coordinate_frame = mavros_msgs::PositionTarget::FRAME_LOCAL_NED;
        target.type_mask = mavros_msgs::PositionTarget::IGNORE_VX |
                           mavros_msgs::PositionTarget::IGNORE_VY |
                           mavros_msgs::PositionTarget::IGNORE_VZ |
                           mavros_msgs::PositionTarget::IGNORE_AFX |
                           mavros_msgs::PositionTarget::IGNORE_AFY |
                           mavros_msgs::PositionTarget::IGNORE_AFZ |
                           mavros_msgs::PositionTarget::IGNORE_YAW_RATE |
                           mavros_msgs::PositionTarget::FORCE;
        target.position.x = -position.y;
        target.position.y = position.x;
        target.position.z = position.z;
        tf2::Quaternion q;
        tf2::fromMsg(telemetry.odom.pose.pose.orientation, q);
        double roll, pitch, yaw;
        tf2::Matrix3x3(q).getRPY(roll, pitch, yaw);
        target.yaw = yaw + M_PI / 2.0;
    }
    g_mavros->updateCommand(target);
}

void runSequential(mission_sequence::Request request) {
    std::string status = "FAILURE", reason;
    bool recovery_required = false;
    bool telemetry_lost = false;
    {
        std::lock_guard<std::mutex> lock(g_session_mutex);
        if (g_pending_aborts.erase({request.session, request.id})) g_sequential_abort = true;
    }
    const bool landing = request.command == "land" || request.command == "emergency_land";
    Tree tree;
    auto command_board = BT::Blackboard::create();
    try {
        std::string xml = buildXmlFromCommands({request.command});
        g_blackboard->cloneInto(*command_board);
        tree = g_factory_ptr->createTreeFromText(xml, command_board);
        StdCoutLogger logger(tree);
        NodeStatus result = NodeStatus::RUNNING;
        const auto deadline = std::chrono::steady_clock::now() +
            std::chrono::duration<double>(g_command_timeout_s);
        while (ros::ok() && result == NodeStatus::RUNNING) {
            const auto telemetry = snapshot();
            if (telemetry.state_fresh && telemetry.state.connected) {
                std::lock_guard<std::mutex> lock(g_session_mutex);
                g_last_known_armed = telemetry.state.armed;
            }
            if (!mission_sequence::telemetryHealthy(telemetry.state_fresh,
                    telemetry.state.connected, telemetry.state.armed, telemetry.odom_fresh,
                    request.command == "takeoff", landing, request.command == "emergency_land", telemetry.state.mode)) {
                status = "FAILURE";
                reason = "TELEMETRY_LOST_DURING_COMMAND; " + telemetry.diagnostics();
                ROS_ERROR("%s", reason.c_str());
                telemetry_lost = true;
                recovery_required = true;
                tree.haltTree();
                const bool fallback_sent = requestAutoLand();
                reason += fallback_sent ? "; AUTO_LAND_REQUESTED" : "; AUTO_LAND_REQUEST_FAILED";
                break;
            }
            if (g_sequential_abort || std::chrono::steady_clock::now() >= deadline) {
                status = g_sequential_abort ? "ABORTED" : "TIMEOUT";
                if (landing) recovery_required = true;
                tree.haltTree();
                if (landing) {
                    reason = requestAutoLand() ? "AUTO_LAND_REQUESTED" : "AUTO_LAND_REQUEST_FAILED";
                } else holdCurrentPosition();
                break;
            }
            result = tree.tickOnce();
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
        }
        if (result != NodeStatus::RUNNING && !telemetry_lost) {
            status = result == NodeStatus::SUCCESS ? "SUCCESS" : "FAILURE";
            if (!landing) mission_sequence::holdAfterFlightCommand(
                request.command, result == NodeStatus::SUCCESS, holdCurrentPosition);
            else if (status == "FAILURE") {
                recovery_required = true;
                reason = requestAutoLand() ? "AUTO_LAND_REQUESTED" : "AUTO_LAND_REQUEST_FAILED";
            }
        } else if (status == "FAILURE" && !telemetry_lost) {
            tree.haltTree();
            if (landing) {
                recovery_required = true;
                reason = requestAutoLand() ? "ROS_SHUTDOWN; AUTO_LAND_REQUESTED" :
                                             "ROS_SHUTDOWN; AUTO_LAND_REQUEST_FAILED";
            } else {
                holdCurrentPosition();
                reason = "ROS_SHUTDOWN";
            }
        }
    } catch (const std::exception& e) {
        status = "FAILURE";
        reason = e.what();
        try { tree.haltTree(); }
        catch (const std::exception& halt_error) { reason += std::string("; HALT_FAILED:") + halt_error.what(); }
        if (landing) {
            recovery_required = true;
            if (!requestAutoLand()) reason += "; AUTO_LAND_REQUEST_FAILED";
            else reason += "; AUTO_LAND_REQUESTED";
        } else {
            try { holdCurrentPosition(); }
            catch (const std::exception& hold_error) {
                reason += std::string("; HOLD_FAILED:") + hold_error.what();
                if (!requestAutoLand()) reason += "; AUTO_LAND_REQUEST_FAILED";
                else reason += "; AUTO_LAND_REQUESTED";
                recovery_required = true;
            }
        }
        ROS_ERROR("Sequential command failed: %s", reason.c_str());
    }
    std::lock_guard<std::mutex> lock(g_session_mutex);
    bool frame_available = false, plan_available = false;
    if (status == "SUCCESS" && request.command == "cross_frame") {
        try {
            const auto frame = command_board->get<Position3D>("frame_center");
            const auto plan = command_board->get<Position3D>("planning_end_pos");
            if (!std::isfinite(frame.x) || !std::isfinite(frame.y) || !std::isfinite(frame.z) ||
                !std::isfinite(plan.x) || !std::isfinite(plan.y) || !std::isfinite(plan.z))
                throw std::runtime_error("NONFINITE_FRAME_PLAN");
            frame_available = plan_available = true;
            command_board->cloneInto(*g_blackboard);
        } catch (const std::exception& e) {
            status = "FAILURE";
            reason = std::string("MISSING_FRAME_PLAN:") + e.what();
        }
    }
    if (status == "SUCCESS") {
        const auto telemetry = snapshot();
        if (telemetry.state_fresh && telemetry.state.connected)
            g_last_known_armed = telemetry.state.armed;
        if (!mission_sequence::telemetryHealthy(telemetry.state_fresh, telemetry.state.connected,
                telemetry.state.armed, telemetry.odom_fresh, request.command == "takeoff", landing,
                request.command == "emergency_land", telemetry.state.mode)) {
            status = "FAILURE";
            reason = "TELEMETRY_STALE_AFTER_COMMAND; " + telemetry.diagnostics();
            ROS_ERROR("%s", reason.c_str());
            recovery_required = true;
        } else if (request.command == "takeoff" &&
                   (!telemetry.state.armed || telemetry.state.mode != "OFFBOARD")) {
            status = "FAILURE";
            reason = "NOT_ARMED_OFFBOARD_AFTER_TAKEOFF; " + telemetry.diagnostics();
            ROS_ERROR("%s", reason.c_str());
        } else if (landing && telemetry.state.armed) {
            status = "FAILURE";
            reason = "STILL_ARMED_AFTER_LAND; " + telemetry.diagnostics();
            ROS_ERROR("%s", reason.c_str());
        }
    }
    if (status != "SUCCESS") recovery_required = true;
    if (recovery_required) g_session->requireRecovery();
    g_session->complete(status == "SUCCESS", frame_available, plan_available);
    if (request.command.rfind("hit_balloon:", 0) == 0 && status == "SUCCESS")
        reason = "ATTEMPTED_UNVERIFIED";
    g_session->recordTerminal(request.id, request.command, status, reason);
    publishStatus(request.session, request.id, request.command, status, reason);
}

void sequentialRequestCallback(const std_msgs::String::ConstPtr& msg) {
    mission_sequence::Request request;
    try {
        const auto payload = json::parse(msg->data);
        if (!payload.is_object() || payload.at("protocol") != 1 ||
            payload.size() != 5u ||
            (payload.contains("reset") == payload.contains("command")) ||
            (payload.contains("reset") && payload.at("reset") != true))
            throw std::invalid_argument("INVALID_PROTOCOL");
        request.epoch = payload.at("server_epoch").get<std::string>();
        request.session = payload.at("session_id").get<std::string>();
        request.id = payload.at("request_id").get<std::string>();
        if (payload.contains("reset")) request.reset = payload.at("reset").get<bool>();
        if (payload.contains("command")) request.command = payload.at("command").get<std::string>();
    } catch (const std::exception& e) {
        ROS_ERROR("Invalid sequential request: %s", e.what());
        publishStatus("", "", "", "REJECTED", "INVALID_REQUEST");
        return;
    }
    std::lock_guard<std::mutex> worker_lock(g_worker_mutex);
    {
        std::lock_guard<std::mutex> lock(g_session_mutex);
        auto decision = g_session->replay(request);
        if (decision.reason != "NEW_REQUEST") {
            if (decision.reason == "REQUEST_ID_CONFLICT") {
                ROS_WARN("Conflicting payload for request ID %s", request.id.c_str());
                return;
            }
            publishStatus(request.session, request.id, request.command,
                          decision.accepted ? decision.reason : "REJECTED",
                          decision.replay && decision.reason != "ACCEPTED" ?
                              g_session->outcomeReason(request.id) : decision.reason);
            return;
        }
        if (g_session->busy()) {
            auto busy_decision = g_session->receive(request, false);
            publishStatus(request.session, request.id, request.command, "REJECTED", busy_decision.reason);
            return;
        }
    }
    if (g_worker.joinable()) g_worker.join();
    std::lock_guard<std::mutex> lock(g_session_mutex);
    const auto telemetry = snapshot();
    if (telemetry.state_fresh && telemetry.state.connected) {
        g_last_known_armed = telemetry.state.armed;
        if (!g_last_known_armed) g_idle_land_requested = false;
    }
    if (mission_sequence::idleRecoveryNeeded(g_session->busy(), g_last_known_armed,
            telemetry.state_fresh, telemetry.state.connected, telemetry.odom_fresh,
            telemetry.state.mode))
        g_session->requireRecovery();
    const bool disarmed = g_session->observeState(telemetry.state_fresh,
        telemetry.state.connected, telemetry.state.armed, telemetry.state.mode);
    auto decision = g_session->receive(request, disarmed);
    if (!decision.accepted) {
        publishStatus(request.session, request.id, request.command, "REJECTED", decision.reason);
        return;
    }
    if (decision.replay) {
        publishStatus(request.session, request.id, request.command, decision.reason,
                      decision.reason == "ACCEPTED" ? "" : g_session->outcomeReason(request.id));
        return;
    }
    if (request.reset) {
        g_pending_aborts.clear();
        g_blackboard = BT::Blackboard::create();
        g_session->recordTerminal(request.id, "", "SUCCESS", "RESET");
        publishStatus(request.session, request.id, "", "SUCCESS", "RESET");
        return;
    }
    if (!mission_sequence::telemetryHealthy(telemetry.state_fresh, telemetry.state.connected,
            telemetry.state.armed, telemetry.odom_fresh, request.command == "takeoff",
            request.command == "land" || request.command == "emergency_land",
            request.command == "emergency_land", telemetry.state.mode)) {
        publishStatus(request.session, request.id, request.command, "ACCEPTED");
        g_session->complete(false);
        g_session->requireRecovery();
        const std::string reason = "TELEMETRY_NOT_READY; " + telemetry.diagnostics();
        ROS_ERROR("%s", reason.c_str());
        g_session->recordTerminal(request.id, request.command, "FAILURE", reason);
        publishStatus(request.session, request.id, request.command, "FAILURE", reason);
        return;
    }
    g_sequential_abort = false;
    publishStatus(request.session, request.id, request.command, "ACCEPTED");
    try {
        g_worker = std::thread(runSequential, request);
    } catch (const std::exception& e) {
        g_session->complete(false);
        g_session->requireRecovery();
        g_session->recordTerminal(request.id, request.command, "FAILURE", e.what());
        publishStatus(request.session, request.id, request.command, "FAILURE", e.what());
    }
}

void sequentialAbortCallback(const std_msgs::String::ConstPtr& msg) {
    try {
        auto payload = json::parse(msg->data);
        const auto session = payload.at("session_id").get<std::string>();
        const auto id = payload.at("request_id").get<std::string>();
        std::lock_guard<std::mutex> lock(g_session_mutex);
        if (payload.at("protocol") != 1) {
            publishStatus(session, id, "", "REJECTED", "INVALID_ABORT");
            return;
        }
        auto decision = g_session->cancel(payload.at("server_epoch").get<std::string>(), session, id);
        if (!decision.accepted) {
            publishStatus(session, id, "", "REJECTED", decision.reason);
            return;
        }
        if (decision.reason == "ABORT_REQUESTED") {
            g_sequential_abort = true;
            g_pending_aborts.insert({session, id});
        }
    } catch (const std::exception& e) {
        ROS_ERROR("Invalid abort request: %s", e.what());
        publishStatus("", "", "", "REJECTED", "INVALID_ABORT");
    }
}

//==============================================================================
// 主函数
//==============================================================================

int main(int argc, char** argv) {
    // 1. 信号处理器注册
    registerSignalHandlers();
    
    // 2. ROS 初始化
    ros::init(argc, argv, "mission");
    for (int i = 1; i < argc; ++i) {
        if (std::string(argv[i]) == "--check-plugins" || std::string(argv[i]) == "--check-stage-trees") {
            BehaviorTreeFactory factory;
            registerPlugins(factory, loadPluginLibraries());
            if (!validateSequentialTrees(factory, true)) return 1;
            std::cout << "sequential_plugin_preflight_passed=1" << std::endl;
            return 0;
        }
    }
    ros::NodeHandle nh;
    ros::NodeHandle nh_private("~");
    
    ROS_INFO("=== Behavior Tree Mission Node Started ===");
    
    // 3. 初始化 MAVROS 连接管理器
    auto mavros_connector = MavRosConnect::getInstance(
        std::make_shared<ros::NodeHandle>(nh)
    );
    
    // 4. 加载配置
    BehaviorTreeConfig config = loadConfiguration(nh_private);
    
    // 5. 加载插件
    std::vector<std::string> plugin_files = loadPluginLibraries();
    
    // 6. 创建行为树工厂并注册插件
    BehaviorTreeFactory factory;
    registerPlugins(factory, plugin_files);
    
    // 7. 如果需要生成 XML 模型文件，生成后退出
    if (config.generate_xml) {
        if (generateNodeModelXML(factory, config.xml_output_file)) {
            ROS_INFO("XML generation completed. Exiting.");
            return 0;
        } else {
            ROS_ERROR("XML generation failed.");
            return 1;
        }
    }
    
    // ========== 根据模式运行 ==========
    
    if (config.mode == "llm") {
        if (!validateSequentialTrees(factory)) {
            ROS_FATAL("Sequential tree preflight failed; mission requests remain disabled");
            return 1;
        }
        bool validate_only = false;
        nh_private.param<bool>("validate_only", validate_only, false);
        if (validate_only) {
            ROS_INFO("sequential_tree_preflight_passed=1; no trees ticked or requests accepted");
            return 0;
        }
        g_factory_ptr = &factory;
        g_mavros = mavros_connector;
        g_blackboard = BT::Blackboard::create();
        g_session.reset(new mission_sequence::Session(makeEpoch()));
        nh_private.param<double>("command_timeout_s", g_command_timeout_s, 120.0);
        if (g_command_timeout_s <= 0) {
            ROS_FATAL("command_timeout_s must be positive");
            return 1;
        }
        const auto* topics = g_mavros->getParam();
        ros::Subscriber state_snapshot_sub = nh.subscribe(topics->fcu_state_topic, 10, stateSnapshotCallback);
        ros::Subscriber odom_snapshot_sub = nh.subscribe(topics->fcu_odom_topic, 10, odomSnapshotCallback);
        g_set_mode = nh.serviceClient<mavros_msgs::SetMode>(topics->set_mode_service);
        g_status_pub = nh.advertise<std_msgs::String>("/mission_status", 20, false);
        g_ready_pub = nh.advertise<std_msgs::String>("/mission_ready", 1, true);
        ros::Subscriber cmd_sub = nh.subscribe("/mission_request", 1, sequentialRequestCallback);
        ros::Subscriber abort_sub = nh.subscribe("/mission_abort", 10, sequentialAbortCallback);
        g_idle_watchdog = std::thread(idleAutoLandWorker);
        ros::Timer ready_timer = nh.createTimer(ros::Duration(1.0), publishReady);
        ROS_INFO("Sequential protocol ready on /mission_request; epoch=%s", g_session->epoch().c_str());
        ros::AsyncSpinner spinner(ASYNC_SPINNER_THREADS);
        spinner.start();
        ros::waitForShutdown();
        spinner.stop();
        {
            std::lock_guard<std::mutex> lock(g_idle_mutex);
            g_idle_shutdown = true;
        }
        g_idle_cv.notify_one();
        if (g_idle_watchdog.joinable()) g_idle_watchdog.join();
        g_sequential_abort = true;
        if (g_worker.joinable()) g_worker.join();
        
    } else {
        // ---- Static 模式：原有行为 ----
        ROS_INFO("=== Running in Static mode ===");
        
        // 8. 从配置文件创建行为树
        Tree tree;
        try {
            tree = factory.createTreeFromFile(config.tree_config_path);
            ROS_INFO("Behavior tree loaded successfully from: %s", config.tree_config_path.c_str());
            
            // 打印黑板参数（用于调试）
            ROS_INFO("=== Blackboard Parameters ===");
            tree.rootBlackboard()->debugMessage();
            
        } catch (const std::exception& e) {
            ROS_FATAL("Failed to create behavior tree: %s", e.what());
            return 1;
        }
        
        // 9. 启用日志记录（可选）
        StdCoutLogger logger(tree);
        
        // 10. 启动异步回调处理线程
        ros::AsyncSpinner spinner(ASYNC_SPINNER_THREADS);
        spinner.start();
        ROS_INFO("AsyncSpinner started with %d threads", ASYNC_SPINNER_THREADS);
        
        // 11. 执行行为树（阻塞直到任务完成）
        ROS_INFO("=== Starting Behavior Tree Execution ===");
        tree.tickWhileRunning();
        ROS_INFO("=== Behavior Tree Execution Completed ===");
        
        // 12. 清理和退出
        spinner.stop();
    }
    
    ROS_INFO("Mission node shutting down.");
    return 0;
}
