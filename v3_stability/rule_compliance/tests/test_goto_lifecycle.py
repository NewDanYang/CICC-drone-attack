"""Compile the deployed GoTo source against a minimal ROS/BT boundary double."""
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[3]
DEPLOY = pathlib.Path(__file__).resolve().parents[1] / "deploy"

STUB = r'''
#pragma once
#include <any>
#include <cassert>
#include <cmath>
#include <limits>
#include <map>
#include <memory>
#include <string>
#include <vector>
#include <chrono>
#define M_PI 3.14159265358979323846
#define ROS_INFO(...) ((void)0)
#define ROS_ERROR(...) ((void)0)
namespace geometry_msgs { struct Point { double x=0,y=0,z=0; }; }
struct Position3D { double x=0,y=0,z=0; };
struct Blackboard {
 std::map<std::string,std::any> data;
 template<class T> bool get(const std::string& k,T& out) { auto i=data.find(k); if(i==data.end()) return false; out=std::any_cast<T>(i->second); return true; }
 template<class T> void set(const std::string& k,T v) { data[k]=v; }
};
struct NodeConfig { std::shared_ptr<Blackboard> blackboard; std::map<std::string,std::any> inputs; };
struct Port {};
using PortsList=std::vector<Port>;
template<class T,class... Args> Port InputPort(Args...) { return {}; }
enum class NodeStatus { RUNNING, SUCCESS, FAILURE };
template<class T> struct Result { bool present; T v; explicit operator bool()const{return present;} T value()const{return v;} };
struct Quaternion { double x=0,y=0,z=0,w=1; };
struct Odom { struct { struct { geometry_msgs::Point position; Quaternion orientation; } pose; } pose; };
namespace ros { struct NodeHandle { template<class T> void param(const char*,T& v,T d){v=d;} }; }
namespace PoseUtils { inline double getYawFromQuat(Quaternion q){return q.z;} }
class DroneActionNode {
 NodeConfig cfg; std::string node_name;
public:
 Odom odom; Odom* fcu_odom_ptr=&odom;
 geometry_msgs::Point published; double published_yaw=0; int publish_count=0; bool hover=false; bool actual_arrival=true;
 DroneActionNode(const std::string& n,const NodeConfig& c):cfg(c),node_name(n){}
 virtual ~DroneActionNode()=default;
 virtual NodeStatus onStart()=0; virtual NodeStatus onRunning()=0;
 const NodeConfig& config(){return cfg;} const std::string& name(){return node_name;}
 template<class T> Result<T> getInput(const std::string& k){
 auto i=cfg.inputs.find(k); if(i!=cfg.inputs.end()) return {true,std::any_cast<T>(i->second)};
 if(k=="frame") return fallback<T>(0);
 if(k=="max_speed" || k=="yaw_rate") return fallback<T>(0.5);
 if(k=="continue_previous") return fallback<T>(false);
 return {false,T{}};
 }
 template<class T,class V> Result<T> fallback(V v){if constexpr(std::is_arithmetic<T>::value)return {true,static_cast<T>(v)};else return {false,T{}};}
 void publishPosition(const geometry_msgs::Point& p,double y){published=p;published_yaw=y;++publish_count;}
 void sendHoverCommand(){hover=true;}
 bool checkArrival(const geometry_msgs::Point&,double,double,double){return actual_arrival;}
};
struct Factory { template<class T> void registerNodeType(const char*){} };
#define BT_REGISTER_NODES(factory) void register_nodes(Factory& factory)
'''

MAIN = r'''
int main(){
 auto bb=std::make_shared<Blackboard>();
 NodeConfig first{bb,{{"goal",Position3D{0.02,0,0}}}};
 GoTo a("a",first);
 assert(a.onStart()==NodeStatus::RUNNING);
 assert(a.published.x==0);
 assert(a.onRunning()==NodeStatus::RUNNING);
 a.last_loop_time-=std::chrono::seconds(10);
 assert(a.onRunning()==NodeStatus::SUCCESS);
 assert(a.published.x==0.02 && !a.hover);
 NodeConfig next{bb,{{"continue_previous",true},{"yaw",1.0}}};
 GoTo b("b",next);
 b.odom.pose.pose.position.x=-0.15;
 assert(b.onStart()==NodeStatus::RUNNING);
 assert(b.published.x==0.02 && b.target_pos.x==0.02);
 b.last_loop_time-=std::chrono::seconds(10);
 assert(b.onRunning()==NodeStatus::RUNNING);
 assert(b.published.x==0.02 && b.published_yaw<=0.05+1e-6);
 NodeConfig invalid{bb,{{"yaw_rate",0.0}}};
 GoTo c("c",invalid);
 assert(c.onStart()==NodeStatus::FAILURE && c.hover);
 NodeConfig nan_goal{bb,{{"goal",Position3D{std::numeric_limits<double>::quiet_NaN(),0,0}}}};
 GoTo nan_goal_node("nan_goal",nan_goal);
 assert(nan_goal_node.onStart()==NodeStatus::FAILURE && nan_goal_node.hover && nan_goal_node.publish_count==0);
 NodeConfig inf_yaw{bb,{{"yaw",std::numeric_limits<double>::infinity()}}};
 GoTo inf_yaw_node("inf_yaw",inf_yaw);
 assert(inf_yaw_node.onStart()==NodeStatus::FAILURE && inf_yaw_node.hover && inf_yaw_node.publish_count==0);
 NodeConfig nan_tolerance{bb,{{"tolerance",std::numeric_limits<double>::quiet_NaN()}}};
 GoTo nan_tolerance_node("nan_tolerance",nan_tolerance);
 assert(nan_tolerance_node.onStart()==NodeStatus::FAILURE && nan_tolerance_node.hover);
 GoTo negative_yaw_tolerance("negative_yaw_tolerance",NodeConfig{bb,{{"yaw_tolerance",-0.1}}});
 assert(negative_yaw_tolerance.onStart()==NodeStatus::FAILURE && negative_yaw_tolerance.hover);
 GoTo inf_speed("inf_speed",NodeConfig{bb,{{"max_speed",std::numeric_limits<double>::infinity()}}});
 assert(inf_speed.onStart()==NodeStatus::FAILURE && inf_speed.hover);
 GoTo overflow_goal("overflow_goal",NodeConfig{bb,{{"goal",Position3D{std::numeric_limits<double>::max(),0,0}}}});
 overflow_goal.odom.pose.pose.position.x=-std::numeric_limits<double>::max();
 assert(overflow_goal.onStart()==NodeStatus::FAILURE && overflow_goal.hover);
 NodeConfig huge_yaw{bb,{{"yaw",std::numeric_limits<double>::max()}}};
 GoTo huge_yaw_node("huge_yaw",huge_yaw);
 assert(huge_yaw_node.onStart()==NodeStatus::RUNNING);
 assert(std::isfinite(huge_yaw_node.published_yaw));
 huge_yaw_node.last_loop_time-=std::chrono::seconds(10);
 assert(huge_yaw_node.onRunning()==NodeStatus::RUNNING);
 assert(std::isfinite(huge_yaw_node.published_yaw));
 GoTo invalid_odom("invalid_odom",NodeConfig{bb,{}});
 invalid_odom.odom.pose.pose.position.x=std::numeric_limits<double>::quiet_NaN();
 assert(invalid_odom.onStart()==NodeStatus::FAILURE && !invalid_odom.hover && invalid_odom.publish_count==0);
 GoTo invalid_quat("invalid_quat",NodeConfig{bb,{}});
 invalid_quat.odom.pose.pose.orientation.x=std::numeric_limits<double>::infinity();
 assert(invalid_quat.onStart()==NodeStatus::FAILURE && !invalid_quat.hover && invalid_quat.publish_count==0);
 GoTo::Handoff old{{4,5,6},0,std::chrono::steady_clock::now()-std::chrono::seconds(1)};
 bb->set("goto_motion_handoff",old);
 GoTo d("d",next);
 d.odom.pose.pose.position.x=0.3;
 assert(d.onStart()==NodeStatus::RUNNING && d.published.x==0.3);
}
'''


class GoToLifecycleTest(unittest.TestCase):
    def test_deployed_source_lifecycle(self):
        compiler = ROOT / ".local-toolchain/zig-windows-x86_64-0.13.0/zig.exe"
        if not compiler.exists():
            self.skipTest("local Zig compiler unavailable")
        with tempfile.TemporaryDirectory() as temp:
            stage = pathlib.Path(temp)
            (stage / "nodes/action").mkdir(parents=True)
            (stage / "base").mkdir()
            (stage / "utils").mkdir()
            (stage / "base/drone_action_node.h").write_text(STUB, encoding="utf-8")
            (stage / "utils/pose_utils.h").write_text("", encoding="utf-8")
            for name in ("goto.h", "goto_ramp.hpp"):
                (stage / "nodes/action" / name).write_bytes((DEPLOY / name).read_bytes())
            source = '#include "base/drone_action_node.h"\n#define private public\n'
            source += (DEPLOY / "goto.cpp").read_text(encoding="utf-8")
            source += '\n#undef private\n' + MAIN
            (stage / "test.cpp").write_text(source, encoding="utf-8")
            executable = stage / "test.exe"
            subprocess.run([str(compiler), "c++", "-std=c++17", "-I", str(stage),
                            str(stage / "test.cpp"), "-o", str(executable)], check=True)
            subprocess.run([str(executable)], check=True)


if __name__ == "__main__":
    unittest.main()
