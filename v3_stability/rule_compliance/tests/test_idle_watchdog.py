"""Exercise the deployed READY timer and idle AUTO.LAND worker without ROS."""
import pathlib
import subprocess
import tempfile
import unittest
from compiler_support import compiler_command

ROOT = pathlib.Path(__file__).resolve().parents[3]
DEPLOY = pathlib.Path(__file__).resolve().parents[1] / "deploy"

STUB = r'''
#include <cassert>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include "sequence_session.hpp"
#include "nlohmann_json.hpp"
using json = nlohmann::json;
#define ROS_ERROR(...) ((void)0)
namespace ros { struct TimerEvent {}; }
namespace std_msgs { struct String { std::string data; }; }
struct State { bool connected=false, armed=false; std::string mode; };
struct Telemetry {
 State state;
 bool state_fresh=false, odom_fresh=false;
 std::string diagnostics() const { return "stub"; }
};
Telemetry observed;
std::mutex g_session_mutex, g_worker_mutex, g_idle_mutex;
std::condition_variable g_idle_cv;
std::thread g_idle_watchdog;
bool g_idle_pending=false, g_idle_shutdown=false, g_idle_land_requested=false, g_last_known_armed=false;
std::unique_ptr<mission_sequence::Session> g_session(new mission_sequence::Session("epoch"));
struct Publisher {
 std::mutex mutex;
 std::string latest;
 void publish(const std_msgs::String& msg) { std::lock_guard<std::mutex> lock(mutex); latest=msg.data; }
 json read() { std::lock_guard<std::mutex> lock(mutex); return json::parse(latest); }
} g_ready_pub;
Telemetry snapshot() { return observed; }
std::mutex service_mutex;
std::condition_variable service_cv;
bool service_entered=false, service_release=false;
std::atomic<int> service_calls{0};
bool requestAutoLand() {
 ++service_calls;
 std::unique_lock<std::mutex> lock(service_mutex);
 service_entered=true;
 service_cv.notify_all();
 service_cv.wait(lock, [] { return service_release; });
 return true;
}
void setTelemetry(bool fresh, bool connected, bool armed, bool odom, const char* mode) {
 std::lock_guard<std::mutex> lock(g_session_mutex);
 observed={{connected,armed,mode},fresh,odom};
}
void publishReady(const ros::TimerEvent&);
void ready() { publishReady(ros::TimerEvent{}); }
bool waitService() {
 std::unique_lock<std::mutex> lock(service_mutex);
 return service_cv.wait_for(lock,std::chrono::seconds(3),[] { return service_entered; });
}
void releaseService() {
 { std::lock_guard<std::mutex> lock(service_mutex); service_release=true; }
 service_cv.notify_all();
}
'''

MAIN = r'''
int main() {
 g_idle_watchdog=std::thread(idleAutoLandWorker);
 setTelemetry(true,true,false,true,"MANUAL");
 ready();
 assert(g_ready_pub.read().at("state")=="IDLE" && service_calls==0);
 assert(!g_ready_pub.read().at("armed").get<bool>());
 {
  std::lock_guard<std::mutex> lock(g_session_mutex);
  assert(g_session->receive({"epoch","flight","reset","",true},true).accepted);
  assert(g_session->receive({"epoch","flight","takeoff","takeoff"},true).accepted);
 }
 setTelemetry(true,true,true,true,"MANUAL");
 ready();
 assert(g_ready_pub.read().at("state")=="BUSY" && service_calls==0);
 {
  std::lock_guard<std::mutex> lock(g_session_mutex);
  g_session->complete(true);
 }
 setTelemetry(true,true,true,true,"OFFBOARD");
 ready();
 assert(g_ready_pub.read().at("state")=="IDLE" && service_calls==0);
 setTelemetry(true,true,true,false,"OFFBOARD");
 ready();
 assert(waitService());
 assert(g_ready_pub.read().at("state")=="RECOVERY_REQUIRED");
 assert(!g_ready_pub.read().at("odom_fresh").get<bool>());
 // A blocked SetMode call cannot hold the session mutex or stop READY publication.
 setTelemetry(false,false,false,false,"MANUAL");
 ready();
 assert(g_ready_pub.read().at("state")=="RECOVERY_REQUIRED");
 assert(g_ready_pub.read().at("armed")==false);
 {
  std::lock_guard<std::mutex> lock(g_session_mutex);
  assert(g_session->receive({"epoch","flight","cross","cross_frame"}).reason=="RECOVERY_REQUIRED");
  assert(g_last_known_armed);
 }
 for(int i=0;i<3;++i) ready();
 assert(service_calls==1);
 releaseService();
 {
  std::lock_guard<std::mutex> lock(g_idle_mutex);
  g_idle_shutdown=true;
 }
 g_idle_cv.notify_one();
 g_idle_watchdog.join();
 // A fresh disarm cancels a queued watchdog request before its worker gets the service.
 g_idle_shutdown=false; g_idle_pending=false; g_idle_land_requested=false;
 setTelemetry(true,true,true,true,"OFFBOARD");
 ready();
 {
  std::unique_lock<std::mutex> gate(g_worker_mutex);
  g_idle_watchdog=std::thread(idleAutoLandWorker);
  setTelemetry(true,true,true,false,"OFFBOARD");
  ready();
  assert(g_ready_pub.read().at("state")=="RECOVERY_REQUIRED");
  setTelemetry(true,true,false,true,"MANUAL");
  ready();
  assert(!g_last_known_armed && !g_idle_land_requested);
 }
 {
  std::lock_guard<std::mutex> lock(g_idle_mutex);
  g_idle_shutdown=true;
 }
 g_idle_cv.notify_one();
 g_idle_watchdog.join();
 assert(service_calls==1);
}
'''


class IdleWatchdogTest(unittest.TestCase):
    def test_deployed_timer_and_worker(self):
        compiler = compiler_command(ROOT)
        if not compiler:
            self.skipTest("C++17 compiler unavailable")
        source = (DEPLOY / "bt_ros.cpp").read_text(encoding="utf-8")
        includes = ROOT / "official_baseline/catkin_ws/src/mission_pkg/include"
        start = source.index("void publishReady(const ros::TimerEvent&)")
        end = source.index("void holdCurrentPosition()", start)
        actual = source[start:end]
        with tempfile.TemporaryDirectory() as temp:
            stage = pathlib.Path(temp)
            (stage / "test.cpp").write_text(STUB + actual + MAIN, encoding="utf-8")
            output = stage / "test.exe"
            subprocess.run(compiler + ["-std=c++17", "-O0", "-pthread", "-I", str(DEPLOY), "-I", str(includes),
                            str(stage / "test.cpp"), "-o", str(output)], check=True, timeout=90)
            subprocess.run([str(output)], check=True, timeout=15)


if __name__ == "__main__":
    unittest.main()
