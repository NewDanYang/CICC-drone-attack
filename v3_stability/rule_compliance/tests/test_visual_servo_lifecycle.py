"""Exercise the deployed servo implementation at the ROS/BT boundary."""
import pathlib
import subprocess
import tempfile
import unittest
from test_goto_lifecycle import STUB, ROOT, DEPLOY

STUB = STUB.replace('template<class T,class... Args> Port InputPort(Args...) { return {}; }', '''template<class T> Port InputPort(const char*,const char*) { return {}; }
template<class T,class V> Port InputPort(const char*,const V&,const char*) { return {}; }''')
STUB = STUB.replace('NodeConfig cfg; std::string node_name;', 'public: NodeConfig cfg; std::string node_name;')
STUB = STUB.replace('struct Quaternion {', '''struct PixelTarget {
 double center_x=320,center_y=240,width=100,height=100,timestamp=0;
 bool is_detected=false;
 double area()const{return width*height;}
};
namespace ros {
inline double clock_value=100;
struct Duration { double v; double toSec()const{return v;} };
struct Time { double v=0; static Time now(){return {clock_value};} double toSec()const{return v;} bool isZero()const{return v==0;} void fromSec(double s){v=s;} };
inline Duration operator-(Time a,Time b){return {a.v-b.v};}
}
#define ROS_INFO_THROTTLE(...) ((void)0)
#define ROS_WARN_THROTTLE(...) ((void)0)
#define ROS_WARN(...) ((void)0)
struct Quaternion {''')
STUB = STUB.replace('class DroneActionNode {', '''struct Controller { ros::NodeHandle nh; ros::NodeHandle* getROSHandle(){return &nh;} };
class DroneActionNode {''')
STUB = STUB.replace('Odom odom;', 'Controller ctl; Controller* mct=&ctl; Odom odom;')
STUB = STUB.replace('void sendHoverCommand(){', '''double vx=0,vz=0,yr=0; int velocity_count=0;
 void publishVelocityWithYawRate(double x,double,double z,double y){vx=x;vz=z;yr=y;++velocity_count;}
 void sendHoverCommand(){''')
STUB = STUB.replace('inline double getYawFromQuat(Quaternion q){return q.z;}', '''inline double getYawFromQuat(Quaternion q){
 return std::atan2(2*(q.w*q.z+q.x*q.y),1-2*(q.y*q.y+q.z*q.z));
}''')
STUB = STUB.replace('struct Odom {', 'struct Odom { struct { ros::Time stamp; } header;')
MAIN = r'''
NodeConfig configuration(){
 NodeConfig c;
 c.inputs={{"k_p_yaw_rate",0.003},{"k_d_yaw_rate",0.001},{"max_yaw_rate",0.5},{"deadzone_yaw",8.0},{"yaw_feedforward_gain",1.0},
 {"k_p_vz",0.01},{"k_d_vz",0.006},{"max_vz",0.3},{"deadzone_vz",10.0},
 {"forward_velocity",1.0},{"sprint_velocity",1.5},{"sprint_time",1.2},{"data_timeout",1.0},
 {"approach_area_threshold",0.08},{"center_tolerance",0.15},{"search_yaw_rate",0.3},{"target_color",std::string("red")}};
 return c;
}
void observation(VisualServo& s,double stamp,double x=320,double y=240,double w=100,double h=100,bool valid=true){
 ros::clock_value=stamp; s.odom.header.stamp={stamp}; s.cfg.inputs["pixel_target"]=PixelTarget{x,y,w,h,stamp,valid}; s.onRunning();
}
void yaw(VisualServo& s,double angle){s.odom.pose.pose.orientation={0,0,std::sin(angle/2),std::cos(angle/2)};}
void bearing(VisualServo& s,double stamp,double camera_yaw,double world_bearing){
 yaw(s,camera_yaw);
 observation(s,stamp,320+320*std::tan(camera_yaw-world_bearing));
}
double projectedPixel(double camera_yaw,double world_angle){
 const double wx=std::cos(world_angle), wy=std::sin(world_angle);
 const double forward=std::cos(camera_yaw)*wx+std::sin(camera_yaw)*wy;
 const double right=std::sin(camera_yaw)*wx-std::cos(camera_yaw)*wy;
 return 320+320*right/forward;
}
void delayedProjection(double target_rate){
 VisualServo servo("delayed",configuration());servo.onStart();
 std::vector<double> angles;
 double angle=0.12;
 int received=0;
 for(int i=0;i<180;++i){
  const double now=400+i*0.01;
  if(i)angle+=servo.yr*0.01+0.00002*i;
  angles.push_back(angle);
  ros::clock_value=now;servo.odom.header.stamp={now};yaw(servo,angle);
  if(i>=24 && i%12==0){
   const int capture=i-(i%24==0 ? 5 : 9);
   const double stamp=400+(capture+0.4)*0.01;
   const double capture_yaw=angles[capture]+0.4*(angles[capture+1]-angles[capture]);
   servo.cfg.inputs["pixel_target"]=PixelTarget{projectedPixel(capture_yaw,target_rate*(stamp-400)),240,100,100,stamp,true};
   ++received;
  }
  servo.onRunning();
  if(received>=2){
   const double expected=target_rate*(1-std::pow(0.65,received-1));
   assert(std::abs(servo.target_angular_velocity_-expected)<1e-10);
  }
 }
 assert(received>8 && servo.bearing_ready_);
}
int main(){
 VisualServo s("servo",configuration()); s.onStart();
 observation(s,100);
 for(int i=0;i<40;++i){ros::clock_value+=0.01;s.onRunning();}
 assert(s.align_stable_frames_==1 && s.current_state_==VisualServo::ALIGN);
 observation(s,100.5);
 assert(s.current_state_==VisualServo::APPROACHING);
 observation(s,101,320,240,500,400);
 assert(s.current_state_==VisualServo::APPROACHING && s.vx==0); // red heading guard
 s.odom.pose.pose.orientation={0,0,1,0};
 observation(s,101.1,320,240,500,400);
 assert(s.current_state_==VisualServo::SPRINTING);
 observation(s,101.2,320,300,100,100,false);
 assert(s.current_state_==VisualServo::SPRINTING && s.sprint_aborted_);
 const int velocities=s.velocity_count;
 const double held_yaw=s.published_yaw;
 observation(s,101.3,320,240,500,400);
 assert(s.velocity_count==velocities && s.published_yaw==held_yaw);
 observation(s,101.4,320,240,500,400,false);
 ros::clock_value=102.4;
 assert(s.onRunning()==NodeStatus::SUCCESS && s.hover && s.velocity_count==velocities);
 // Reacquisition outside a sprint resets derivatives and observation stability.
 s.onStart();
 int held=s.publish_count;
 observation(s,101.3,320,261);
 assert(std::abs(s.vz+0.11)<1e-8); // reacquisition has no derivative kick
 observation(s,101.4,320,262);
 assert(std::abs(s.vz+0.18)<1e-8); // derivative uses 100 ms, not tick interval
 double command=s.vz;
 for(int i=0;i<8;++i){ros::clock_value+=0.01;s.onRunning();assert(s.vz==command);}
 assert(s.publish_count==held);
 ros::clock_value=102.5;s.onRunning();
 assert(s.search_anchor_active_ && s.current_state_==VisualServo::ALIGN);
 // Previously consumed data cannot revive a lost target.
 ros::clock_value=101.4;s.onRunning();assert(s.isTargetLost());
 // Finite completion reports an attempted sprint, not a physical hit.
 VisualServo completed("completed",configuration()); completed.onStart();
 completed.odom.pose.pose.orientation={0,0,1,0};
 for(int i=0;i<6;++i)observation(completed,200+i*0.1,320,240,500,400);
 assert(completed.current_state_==VisualServo::SPRINTING);
 observation(completed,201.8,320,240,500,400);
 assert(completed.onRunning()==NodeStatus::SUCCESS && completed.hover);
 // Close encounter loss holds position before ending an unverified attempt.
 VisualServo close("close",configuration());close.onStart();yaw(close,M_PI);
 observation(close,700,470,240,400,260);
 assert(close.close_encounter_pending_ && close.current_state_==VisualServo::ALIGN);
 observation(close,700.12,470,240,400,260,false);
 assert(close.onRunning()==NodeStatus::RUNNING && close.publish_count>0);
 ros::clock_value=700.75;
 assert(close.onRunning()==NodeStatus::SUCCESS && close.hover && close.current_state_==VisualServo::ALIGN);
 VisualServo late_loss("late_loss",configuration());late_loss.onStart();yaw(late_loss,M_PI);
 observation(late_loss,705,470,240,400,260);
 observation(late_loss,705.7,470,240,400,260,false);
 ros::clock_value=706.31;
 assert(late_loss.onRunning()==NodeStatus::SUCCESS && late_loss.hover);
 VisualServo reacquired("reacquired",configuration());reacquired.onStart();yaw(reacquired,M_PI);
 observation(reacquired,710,470,240,400,260);
 observation(reacquired,710.12,470,240,400,260,false);
 observation(reacquired,710.35,450,240,100,100);
 assert(!reacquired.close_encounter_pending_ && reacquired.close_encounter_lost_at_.isZero());
 ros::clock_value=711.1;
 assert(reacquired.onRunning()==NodeStatus::RUNNING);
 VisualServo far("far",configuration());far.onStart();
 observation(far,720,470,240,100,100);
 observation(far,720.12,470,240,100,100,false);
 ros::clock_value=721.3;
 assert(far.onRunning()==NodeStatus::RUNNING && !far.close_encounter_pending_);
 VisualServo stale("stale",configuration());stale.onStart();yaw(stale,M_PI);
 observation(stale,725,470,240,400,260);
 ros::clock_value=726.2;
 assert(stale.onRunning()==NodeStatus::RUNNING && !stale.close_encounter_pending_);
 ros::clock_value=727;
 assert(stale.onRunning()==NodeStatus::RUNNING && !stale.hover);
 VisualServo delayed("delayed",configuration());delayed.onStart();yaw(delayed,M_PI);
 ros::clock_value=800.29;delayed.odom.header.stamp={800.29};
 delayed.cfg.inputs["pixel_target"]=PixelTarget{470,240,400,260,800,true};
 delayed.onRunning();
 assert(delayed.close_encounter_pending_ && delayed.close_encounter_stamp_.toSec()==800);
 ros::clock_value=801.20;
 delayed.cfg.inputs["pixel_target"]=PixelTarget{470,240,400,260,800,false};
 assert(delayed.onRunning()==NodeStatus::RUNNING && !delayed.close_encounter_pending_);
 ros::clock_value=801.9;
 assert(delayed.onRunning()==NodeStatus::RUNNING && !delayed.hover);
 VisualServo wrong_heading("wrong_heading",configuration());wrong_heading.onStart();
 observation(wrong_heading,805,470,240,400,260);
 assert(!wrong_heading.close_encounter_pending_);
 observation(wrong_heading,805.12,470,240,400,260,false);
 ros::clock_value=806;
 assert(wrong_heading.onRunning()==NodeStatus::RUNNING && !wrong_heading.hover);
 auto purple_config=configuration();purple_config.inputs["target_color"]=std::string("purple");
 VisualServo purple("purple",purple_config);purple.onStart();
 observation(purple,730,470,240,400,260);
 observation(purple,730.12,470,240,400,260,false);
 ros::clock_value=731.3;
 assert(purple.onRunning()==NodeStatus::RUNNING && !purple.close_encounter_pending_);
 // Ego rotation must cancel image motion for a stationary world target.
 VisualServo stationary("stationary",configuration()); stationary.onStart();
 for(int i=0;i<12;++i){
  bearing(stationary,300+i*0.12,0.15*std::sin(i*0.4),0.0);
  assert(std::abs(stationary.target_angular_velocity_)<1e-12);
 }
 // A moving target contributes its signed world rate in addition to unchanged PD.
 VisualServo moving("moving",configuration()), baseline("baseline",configuration());
 baseline.cfg.inputs["yaw_feedforward_gain"]=0.0;
 moving.onStart();baseline.onStart();
 for(int i=0;i<8;++i){
  bearing(moving,310+i*0.12,0.0,-i*0.012);
  bearing(baseline,310+i*0.12,0.0,-i*0.012);
 }
 assert(moving.target_angular_velocity_<-0.09);
 assert(std::abs(moving.yr-baseline.yr-moving.target_angular_velocity_)<1e-12);
 assert(moving.yr<baseline.yr);
 const double held_rate=moving.target_angular_velocity_, held_command=moving.yr;
 for(int i=0;i<5;++i){ros::clock_value+=0.01;moving.onRunning();}
 assert(moving.target_angular_velocity_==held_rate && moving.yr==held_command);
 moving.onStart();baseline.onStart();
 for(int i=0;i<8;++i){
  bearing(moving,311+i*0.12,0.0,i*0.012);
  bearing(baseline,311+i*0.12,0.0,i*0.012);
 }
 assert(moving.target_angular_velocity_>0.09 && moving.yr>baseline.yr);
 assert(std::abs(moving.yr-baseline.yr-moving.target_angular_velocity_)<1e-12);
 // Crossing the yaw branch cut must produce the small wrapped target rate.
 VisualServo wrapped("wrapped",configuration());wrapped.onStart();
 bearing(wrapped,319.88,3.13,3.13);
 bearing(wrapped,320,3.13,3.13);
 bearing(wrapped,320.12,-3.13,-3.13);
 assert(std::abs(wrapped.target_angular_velocity_-0.35*(2*M_PI-6.26)/0.12)<1e-10);
 double wrapped_mid=0;assert(wrapped.interpolateYaw(320.06,wrapped_mid));
 assert(std::abs(std::abs(wrapped_mid)-M_PI)<1e-10);
 observation(moving,312,320,240,100,100,false);
 assert(!moving.bearing_ready_ && moving.target_angular_velocity_==0);
 bearing(moving,312.12,0,-0.4);
 assert(moving.target_angular_velocity_==0);
 bearing(moving,312.24,0,-0.412);
 assert(moving.target_angular_velocity_<0);
 // A gap longer than the freshness window also reseeds without a spike.
 bearing(moving,314,0,-0.6);
 assert(moving.target_angular_velocity_==0);
 moving.odom.pose.pose.orientation={0,0,0,0};
 observation(moving,314.12,400);
 assert(moving.bearing_pending_ && std::abs(moving.yr-std::clamp(moving.yaw_pd_command_,-0.5,0.5))<1e-12);
 yaw(moving,0);observation(moving,314.24,400);
 assert(moving.target_angular_velocity_==0);
 moving.odom.pose.pose.orientation.x=std::numeric_limits<double>::quiet_NaN();
 observation(moving,314.36,400);
 assert(moving.bearing_pending_ && std::isfinite(moving.yr));
 yaw(moving,0);observation(moving,314.48,std::numeric_limits<double>::infinity());
 assert(!moving.bearing_ready_ && moving.isTargetLost());
 moving.img_fx_=0;observation(moving,314.60,400);
 assert(!moving.bearing_ready_);
 moving.img_fx_=320;
 VisualServo saturated("saturated",configuration());saturated.onStart();
 bearing(saturated,330,0,0);
 for(int i=1;i<10;++i){
  bearing(saturated,330+i*0.001,0,-i*0.1);
  assert(std::abs(saturated.target_angular_velocity_)<=0.5 && std::abs(saturated.yr)<=0.5);
 }
 delayedProjection(0.0);
 delayedProjection(-0.08);
 delayedProjection(0.08);
 // History sampling runs during loss, rejects duplicates and stale/invalid odometry.
 VisualServo history("history",configuration());ros::clock_value=500;history.onStart();
 for(int i=0;i<180;++i){
  ros::clock_value=500+i*0.01;history.odom.header.stamp={ros::clock_value};
  yaw(history,3.13+i*0.002);history.onRunning();
 }
 assert(history.yaw_history_.back().stamp-history.yaw_history_.front().stamp<=1.5);
 const auto count=history.yaw_history_.size();
 history.onRunning();assert(history.yaw_history_.size()==count);
 double interpolated=0;
 assert(history.interpolateYaw(500.115,interpolated)==false);
 assert(history.interpolateYaw(501.795,interpolated)==false);
 assert(history.interpolateYaw(501.115,interpolated));
 assert(std::abs(std::atan2(std::sin(interpolated-(3.13+0.223)),std::cos(interpolated-(3.13+0.223))))<1e-12);
 ros::clock_value=502;history.odom.header.stamp={501.8};history.onRunning();
 assert(history.yaw_history_.back().stamp==501.79);
 history.odom.header.stamp={502};history.odom.pose.pose.orientation={0,0,0,0};history.onRunning();
 assert(history.yaw_history_.back().stamp==501.79);
 yaw(history,0);history.onRunning();
 assert(!history.interpolateYaw(501.9,interpolated)); // no interpolation across a wide gap
 ros::clock_value=502.12;
 history.cfg.inputs["pixel_target"]=PixelTarget{350,240,100,100,502.12,true};history.onRunning();
 assert(!history.bearing_ready_ && std::isfinite(history.yr));
 VisualServo pending("pending",configuration());ros::clock_value=600;pending.onStart();
 pending.odom.header.stamp={599.99};pending.onRunning();
 pending.cfg.inputs["pixel_target"]=PixelTarget{320,240,100,100,600,true};pending.onRunning();
 assert(pending.bearing_pending_ && pending.align_stable_frames_==1);
 const double pd=pending.yaw_pd_command_, prev=pending.prev_err_x_;
 ros::clock_value=600.01;pending.odom.header.stamp={600.01};pending.onRunning();
 assert(!pending.bearing_pending_ && pending.bearing_ready_ && pending.bearing_stamp_==600);
 assert(!pending.new_observation_ && pending.align_stable_frames_==1 && pending.yaw_pd_command_==pd && pending.prev_err_x_==prev);
 pending.onRunning();assert(pending.bearing_stamp_==600 && pending.align_stable_frames_==1);
 ros::clock_value=600.12;pending.odom.header.stamp={600.11};
 pending.cfg.inputs["pixel_target"]=PixelTarget{324,240,100,100,600.12,true};pending.onRunning();
 assert(pending.bearing_pending_);
 const double next_pd=pending.yaw_pd_command_, next_prev=pending.prev_err_x_;
 ros::clock_value=600.13;pending.odom.header.stamp={600.13};pending.onRunning();
 assert(!pending.bearing_pending_ && pending.target_angular_velocity_<0 && pending.yr<next_pd);
 assert(pending.yaw_pd_command_==next_pd && pending.prev_err_x_==next_prev && !pending.new_observation_);
 const double once=pending.target_angular_velocity_;pending.onRunning();assert(pending.target_angular_velocity_==once);
 ros::clock_value=600.24;pending.odom.header.stamp={600.23};
 pending.cfg.inputs["pixel_target"]=PixelTarget{328,240,100,100,600.24,true};pending.onRunning();
 assert(pending.bearing_pending_);
 ros::clock_value=600.40;pending.onRunning();
 assert(!pending.bearing_pending_ && !pending.bearing_ready_ && pending.target_angular_velocity_==0);
 moving.target_angular_velocity_=-100;
 assert(moving.computeYawRate(0,0)==-0.5);
 assert(moving.computeYawRate(1000,0)==-0.5);
 moving.target_angular_velocity_=100;
 assert(moving.computeYawRate(-1000,0)==0.5);
}

'''

class VisualServoLifecycleTest(unittest.TestCase):
    def test_actual_deployed_source(self):
        compiler = ROOT / '.local-toolchain/zig-windows-x86_64-0.13.0/zig.exe'
        self.assertTrue(compiler.exists(), 'local Zig compiler required')
        with tempfile.TemporaryDirectory() as temp:
            stage = pathlib.Path(temp)
            for name in ('nodes/action', 'base', 'utils', 'ros'):
                (stage / name).mkdir(parents=True, exist_ok=True)
            (stage / 'base/drone_action_node.h').write_text(STUB, encoding='utf-8')
            for name in ('utils/pose_utils.h', 'ros/time.h'):
                (stage / name).write_text('', encoding='utf-8')
            (stage / 'nodes/action/visual_servo.h').write_bytes((DEPLOY / 'visual_servo.h').read_bytes())
            source = '#include "base/drone_action_node.h"\n#define private public\n'
            source += (DEPLOY / 'visual_servo.cpp').read_text(encoding='utf-8')
            source += '\n#undef private\n' + MAIN
            (stage / 'test.cpp').write_text(source, encoding='utf-8')
            executable = stage / 'test.exe'
            subprocess.run([str(compiler), 'c++', '-std=c++17', '-I', str(stage), str(stage / 'test.cpp'), '-o', str(executable)], check=True)
            subprocess.run([str(executable)], check=True)

if __name__ == '__main__':
    unittest.main()
