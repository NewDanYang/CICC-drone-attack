"""Compile and exercise the actual PlanningControl implementation without ROS/flight."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
DEPLOY = ROOT / 'v3_stability/rule_compliance/deploy'
STUB = r'''
#pragma once
#include <string>
#include <memory>
#include <vector>
#include <cmath>
#include <cassert>
namespace ros {
inline double clock_now=10, wall_now=10;
struct Duration { double t; double toSec() const { return t; } };
struct Time { double t=0; static Time now(){return {clock_now};} bool isZero()const{return t==0;} };
inline Duration operator-(Time a,Time b){return {a.t-b.t};}
inline bool operator<(Time a,Time b){return a.t<b.t;}
struct WallTime { double t=0; static WallTime now(){return {wall_now};} };
inline Duration operator-(WallTime a,WallTime b){return {a.t-b.t};}
inline int subscribers=0,publishers=1,sends=0;
struct Publisher { int getNumSubscribers()const{return subscribers;} template<class T> void publish(const T&){++sends;} };
struct Subscriber { int getNumPublishers()const{return publishers;} };
struct NodeHandle {
 template<class T> void param(const std::string&,T& out,const T& value){out=value;}
 template<class T> Publisher advertise(const std::string&,int){return {};}
 template<class... T> Subscriber subscribe(T...){return {};}
};
}
namespace geometry_msgs {
struct Point { double x=0,y=0,z=0; };
struct Quaternion { double x=0,y=0,z=0,w=1; };
struct Header { ros::Time stamp; std::string frame_id; };
struct Pose {Point position; Quaternion orientation;};
struct PoseStamped { Header header; Pose pose; };
}
namespace nav_msgs {struct Odometry {geometry_msgs::Header header; struct {geometry_msgs::Pose pose;} pose;};}
namespace quadrotor_msgs {
struct PositionCommand {
 using ConstPtr=std::shared_ptr<const PositionCommand>;
 static constexpr int TRAJECTORY_STATUS_READY=1;
 geometry_msgs::Header header;
 geometry_msgs::Point position,goal_pos;
 double yaw=0; unsigned int trajectory_id=1; int trajectory_flag=1;
};
}
namespace BT {
enum class NodeStatus {RUNNING,SUCCESS,FAILURE};
struct NodeConfig {};
using PortsList=std::vector<int>;
template<class T,class... A> int InputPort(A...){return 0;}
template<class T,class... A> int OutputPort(A...){return 0;}
struct Factory {template<class T>void registerNodeType(const char*){}};
}
using namespace BT;
struct Position3D {double x=0,y=0,z=0;};
inline Position3D input_goal{5.3,1,1.5};
struct Connector {std::shared_ptr<ros::NodeHandle> getROSHandle(){return std::make_shared<ros::NodeHandle>();}};
template<class T>struct Result {T data; operator bool()const{return true;} T value()const{return data;}};
inline nav_msgs::Odometry odom;
inline geometry_msgs::Point output;
inline int holds=0;
class DroneActionNode {
public:
 DroneActionNode(const std::string&,const NodeConfig&){}
 virtual BT::NodeStatus onStart()=0;
 virtual BT::NodeStatus onRunning()=0;
 virtual void onHalted(){}
 template<class T> Result<T> getInput(const char*) {return {T{}};}
 template<class T> void setOutput(const char*,T){}
 std::string name()const{return "PlanningControl";}
 std::shared_ptr<Connector> mct=std::make_shared<Connector>();
 const nav_msgs::Odometry* fcu_odom_ptr=&odom;
 void publishPosition(geometry_msgs::Point p,double){output=p;++holds;}
 bool checkArrival(geometry_msgs::Point p,double tol){return std::hypot(std::hypot(p.x-odom.pose.pose.position.x,p.y-odom.pose.pose.position.y),p.z-odom.pose.pose.position.z)<tol;}
};
template<> inline Result<Position3D> DroneActionNode::getInput<Position3D>(const char*){return {input_goal};}
template<> inline Result<double> DroneActionNode::getInput<double>(const char* key){return {std::string(key)=="tolerance"?0.15:0.0};}
namespace PoseUtils {inline double getYawFromQuat(geometry_msgs::Quaternion){return 0;}}
#define ROS_INFO(...) ((void)0)
#define ROS_ERROR(...) ((void)0)
#define BT_REGISTER_NODES(factory) void register_test(BT::Factory& factory)
'''
HARNESS = r'''
#include "nodes/action/planning_control.h"
#include "planning_control.cpp"
void advance(double dt){ros::clock_now+=dt;ros::wall_now+=dt;}
void reset(){ros::clock_now=ros::wall_now=10;ros::subscribers=0;ros::publishers=1;ros::sends=holds=0;odom={};output={};}
std::shared_ptr<quadrotor_msgs::PositionCommand> command(unsigned id=2){
 auto c=std::make_shared<quadrotor_msgs::PositionCommand>();
 c->header.stamp=ros::Time::now();c->header.frame_id="world";
 c->goal_pos={5.3,1,1.5};c->position={1,0,1};c->trajectory_id=id;return c;
}
int main(){
 // A new tree whose first node is PlanningControl must not publish before TCP connection.
 for(int i=0;i<5;++i){
 reset(); PlanningControl p("p",{});p.onStart();advance(.31);
 assert(p.onRunning()==NodeStatus::RUNNING && ros::sends==0);
 ros::subscribers=1;p.onRunning();assert(ros::sends==1);
 for(int j=0;j<10;++j){advance(.01);p.onRunning();}assert(ros::sends==1);
 p.onHalted();
 }
 reset();PlanningControl connected("p",{});connected.onStart();
 connected.plannerCmdCallback(command(1));ros::subscribers=1;advance(.01);
 assert(connected.onRunning()==NodeStatus::RUNNING && ros::sends==1);
 auto prior=command(1);connected.plannerCmdCallback(prior);connected.onRunning();assert(output.x==0);
 connected.plannerCmdCallback(command(2));connected.onRunning();assert(output.x==1);
 reset();PlanningControl absent("p",{});absent.onStart();advance(3.01);
 assert(absent.onRunning()==NodeStatus::FAILURE && ros::sends==0);
 reset();PlanningControl silent("p",{});silent.onStart();ros::subscribers=1;advance(.31);silent.onRunning();advance(5.01);
 assert(silent.onRunning()==NodeStatus::FAILURE && ros::sends==1 && output.x==0);
 reset(); PlanningControl p("p",{});p.onStart();
 auto old=command(1);old->goal_pos={2.99,-1.05,.9};p.plannerCmdCallback(old);
 ros::subscribers=1;advance(.31);p.onRunning();
 old->header.stamp=ros::Time::now();p.plannerCmdCallback(old);p.onRunning();assert(output.x==0);
 auto c=command();c->header.stamp.t=9;p.plannerCmdCallback(c);p.onRunning();assert(output.x==0);
 c=command(1);p.plannerCmdCallback(c);p.onRunning();assert(output.x==0);
 c=command();c->position.x=NAN;p.plannerCmdCallback(c);p.onRunning();assert(output.x==0);
 c=command();c->header.stamp.t=NAN;p.plannerCmdCallback(c);p.onRunning();assert(output.x==0);
 c=command();c->header.stamp.t=INFINITY;p.plannerCmdCallback(c);p.onRunning();assert(output.x==0);
 c=command();p.plannerCmdCallback(c);p.onRunning();assert(output.x==1);
 advance(.51);odom.pose.pose.position={.8,0,1};assert(p.onRunning()==NodeStatus::FAILURE && output.x==.8 && ros::sends==1);
 reset();PlanningControl success("p",{});success.onStart();ros::subscribers=1;advance(.31);success.onRunning();
 success.plannerCmdCallback(command());odom.pose.pose.position={5.3,1,1.5};assert(success.onRunning()==NodeStatus::SUCCESS);
 reset();PlanningControl halted("p",{});halted.onStart();ros::subscribers=1;advance(.31);halted.onRunning();halted.onHalted();halted.plannerCmdCallback(command());assert(!halted.has_planner_cmd);
}
'''


class PlanningControlTest(unittest.TestCase):
    def test_actual_source_with_mock_transport_and_clock(self):
        compiler = os.environ.get('CXX') or shutil.which('g++') or shutil.which('clang++')
        zig = ROOT / '.local-toolchain/zig-windows-x86_64-0.13.0/zig.exe'
        cmd = [compiler] if compiler else [str(zig), 'c++'] if zig.is_file() else None
        if cmd is None:
            self.skipTest('No C++ compiler available')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ['base/drone_action_node.h', 'quadrotor_msgs/PositionCommand.h',
                         'utils/pose_utils.h', 'tf2/LinearMath/Quaternion.h',
                         'tf2_geometry_msgs/tf2_geometry_msgs.h']:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('#include "stub.h"\n')
            (root / 'stub.h').write_text(STUB)
            header = root / 'nodes/action/planning_control.h'
            header.parent.mkdir(parents=True)
            header.write_text((DEPLOY / 'planning_control.h').read_text().replace('private:', 'public:'))
            (root / 'test.cpp').write_text(HARNESS)
            executable = root / ('test.exe' if os.name == 'nt' else 'test')
            result = subprocess.run(cmd + ['-std=c++17', '-I', str(root), '-I', str(DEPLOY),
                                           str(root / 'test.cpp'), '-o', str(executable)],
                                    capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            subprocess.run([str(executable)], check=True, timeout=30)


if __name__ == '__main__':
    unittest.main()
