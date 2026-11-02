"""Compile the deployed tracker and frozen detector base against ROS/BT doubles."""
import pathlib
import subprocess
import tempfile
import unittest
from compiler_support import compiler_command

ROOT = pathlib.Path(__file__).resolve().parents[3]
DEPLOY = pathlib.Path(__file__).resolve().parents[1] / "deploy"
BASE = ROOT / "official_baseline/catkin_ws/src/mission_pkg"

STUB = r'''
#pragma once
#include <any>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <deque>
#include <limits>
#include <map>
#include <memory>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>
#define ROS_INFO(...) ((void)0)
namespace ros {
inline double source_now=10, wall_now=10;
struct Duration { double t; double toSec() const { return t; } };
struct Time { double t=0; static Time now(){return {source_now};} double toSec()const{return t;} bool isZero()const{return t==0;} };
struct WallTime { double t=0; static WallTime now(){return {wall_now};} };
inline Duration operator-(WallTime a,WallTime b){return {a.t-b.t};}
struct Subscriber {};
struct NodeHandle {
 template<class T> void param(const char*,T& v,T d){v=d;}
 template<class C,class M> Subscriber subscribe(const std::string&,int,void(C::*)(const M&),C*){return {};}
};
}
namespace common_msgs {
struct Header { ros::Time stamp; };
struct Obj { Header header; std::string class_name="red"; uint32_t left_top_x=100,left_top_y=100,right_bottom_x=200,right_bottom_y=200,center_x=150,center_y=150; float score=0.95f; };
struct Objects { using ConstPtr=std::shared_ptr<const Objects>; Header header; std::vector<Obj> objects; };
}
struct PixelTarget { double center_x=0,center_y=0,width=0,height=0,timestamp=0; bool is_detected=false;
 PixelTarget()=default;
 PixelTarget(double x,double y,double w,double h,double t,bool v=false):center_x(x),center_y(y),width(w),height(h),timestamp(t),is_detected(v){}
};
struct NodeConfig {};
using PortsList=std::set<int>;
template<class T,class... A> int InputPort(A...){return 1;}
template<class T,class... A> int OutputPort(A...){return 2;}
enum class NodeStatus { RUNNING,SUCCESS,FAILURE };
using RuntimeError=std::runtime_error;
template<class T> struct Result { T v; operator bool()const{return true;} T value()const{return v;} };
struct Connector { ros::NodeHandle nh; ros::NodeHandle* getROSHandle(){return &nh;} };
class DroneActionNode {
 std::string name_;
protected: std::shared_ptr<Connector> mct=std::make_shared<Connector>();
public:
 PixelTarget output; int writes=0;
 DroneActionNode(const std::string& n,const NodeConfig&):name_(n){}
 virtual ~DroneActionNode()=default;
 virtual NodeStatus onStart()=0; virtual NodeStatus onRunning()=0;
 const std::string& name()const{return name_;}
 template<class T> Result<T> getInput(const std::string& k){
 if constexpr(std::is_same_v<T,std::string>) return {"red"};
 else if constexpr(std::is_same_v<T,int>) return {10};
 else return {0.9};
 }
 void setOutput(const char*,PixelTarget p){output=p;++writes;}
};
struct Factory { template<class T> void registerNodeType(const char*){} };
#define BT_REGISTER_NODES(factory) void register_nodes(Factory& factory)
'''

MAIN = r'''
void clockAt(double t) { ros::source_now=t; ros::wall_now=t; }
void frame(TargetTracker& t,double stamp,std::vector<common_msgs::Obj> objects) {
 auto msg=std::make_shared<common_msgs::Objects>(); msg->header.stamp={stamp}; msg->objects=objects;
 t.objectsCallback(msg); assert(t.onRunning()==NodeStatus::RUNNING);
}
int main(){
 TargetTracker t("tracker",{}); t.onStart(); assert(!t.output.is_detected);
 common_msgs::Obj obj;
 for(int tick=0;tick<100;++tick){
  clockAt(10+tick*0.01);
  if(tick%10==0) frame(t,ros::source_now,{obj});
  else {double timestamp=t.output.timestamp;int writes=t.writes;t.onRunning();assert(t.output.timestamp==timestamp && t.writes==writes);}
  assert(t.output.is_detected);
 }
 assert(t.pixel_history.size()==10);
 const double stamp=t.output.timestamp;
 clockAt(stamp+0.299);t.onRunning();assert(t.output.is_detected);
 clockAt(stamp+0.301);t.onRunning();assert(!t.output.is_detected && t.output.timestamp==stamp && t.pixel_history.empty());
 int writes=t.writes;clockAt(stamp+2);t.onRunning();assert(t.writes==writes && t.output.timestamp==stamp);
 clockAt(20);frame(t,20,{obj});assert(t.output.is_detected);
 clockAt(20.01);frame(t,20.01,{});assert(!t.output.is_detected && t.pixel_history.empty());
 clockAt(21);frame(t,21,{obj});obj.class_name="blue";frame(t,21,{obj});assert(!t.output.is_detected);obj.class_name="red";
 obj.left_top_x=201;frame(t,21,{obj});assert(!t.output.is_detected);obj.left_top_x=100;
 obj.right_bottom_y=100;frame(t,21,{obj});assert(!t.output.is_detected);obj.right_bottom_y=200;
 obj.score=std::numeric_limits<float>::infinity();frame(t,21,{obj});assert(!t.output.is_detected);
 obj.score=std::numeric_limits<float>::quiet_NaN();frame(t,21,{obj});assert(!t.output.is_detected);
 obj.score=0.89f;frame(t,21,{obj});assert(!t.output.is_detected);obj.score=0.95f;
 clockAt(30);frame(t,29.69,{obj});assert(!t.output.is_detected);
 frame(t,30.01,{obj});assert(!t.output.is_detected);
 frame(t,std::numeric_limits<double>::quiet_NaN(),{obj});assert(!t.output.is_detected);
 frame(t,std::numeric_limits<double>::infinity(),{obj});assert(!t.output.is_detected);
 frame(t,29.8,{obj});assert(t.output.is_detected && t.output.timestamp==29.8);
 clockAt(30.11);t.onRunning();assert(!t.output.is_detected);
 clockAt(40);frame(t,0,{obj});assert(t.output.is_detected && t.output.timestamp==40);
 ros::wall_now=40.31;t.onRunning();assert(!t.output.is_detected);
 t.onStart();assert(!t.output.is_detected && t.pixel_history.empty());
}
'''


class TargetTrackerTest(unittest.TestCase):
    def test_deployed_tracker_with_actual_base(self):
        compiler = compiler_command(ROOT)
        if not compiler:
            self.skipTest("C++17 compiler unavailable")
        with tempfile.TemporaryDirectory() as temp:
            stage = pathlib.Path(temp)
            for directory in ("base", "common_msgs", "nodes/perception"):
                (stage / directory).mkdir(parents=True)
            (stage / "base/drone_action_node.h").write_text(STUB, encoding="utf-8")
            (stage / "common_msgs/Objects.h").write_text('#include "base/drone_action_node.h"\n', encoding="utf-8")
            (stage / "base/target_detector_base.h").write_bytes(
                (BASE / "include/base/target_detector_base.h").read_bytes())
            (stage / "nodes/perception/target_tracker.h").write_bytes((DEPLOY / "target_tracker.h").read_bytes())
            source = (BASE / "src/base/target_detector_base.cpp").read_text(encoding="utf-8")
            source += '\n#define private public\n' + (DEPLOY / "target_tracker.cpp").read_text(encoding="utf-8")
            source += '\n' + MAIN + '\n#undef private\n'
            (stage / "test.cpp").write_text(source, encoding="utf-8")
            exe = stage / "test.exe"
            subprocess.run(compiler + ["-std=c++17", "-I", str(stage),
                            str(stage / "test.cpp"), "-o", str(exe)], check=True)
            subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    unittest.main()
