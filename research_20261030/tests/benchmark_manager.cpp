#include <plan_manage/planner_manager.h>
#include "../planner/ego_adapter.hpp"
#include <fstream>
#include <iomanip>
using namespace ego_planner;
int main(int argc,char**argv){
  if(argc<2||argc>3)return 2;
  std::string mode=argc==3?argv[2]:"all";
  std::ofstream out(argv[1]);out<<std::setprecision(12);
  out<<"scene,distance,success,original_s,candidate_s,accepted,max_vel_before,max_vel_after,start_acc,end_acc,added_ms,rms_jerk_before,rms_jerk_after\n";
  ros::NodeHandle nh;nh.params={{"manager/max_vel",0.3},{"manager/max_acc",0.5},{"manager/max_jerk",4},
    {"manager/control_points_distance",0.1},{"manager/feasibility_tolerance",0.05},{"manager/planning_horizon",5},
    {"optimization/lambda_smooth",1},{"optimization/lambda_collision",5},{"optimization/lambda_feasibility",0.1},
    {"optimization/lambda_fitness",1},{"optimization/dist0",0.1},{"optimization/max_vel",0.3},{"optimization/max_acc",0.5}};
  if(mode=="runtime")nh.params["manager/certified_shortcut"]=1;
  EGOPlannerManager manager;manager.initPlanModules(nh,std::make_shared<PlanningVisualization>());
  for(int scene=0;scene<3;++scene)for(double d:{0.5,1.,2.,3.,4.}){
    manager.grid_map_->obstacles.clear();manager.grid_map_->unknown=scene==2;
    if(scene==1)manager.grid_map_->obstacles.push_back({{d/2-0.12,-0.25,0.6},{d/2+0.12,0.25,1.4}});
    bool ok=manager.reboundReplan({0,0,1},{0,0,0},{0,0,0},{d,0,1},{0,0,0},true,false);
    if(!ok){out<<scene<<","<<d<<",0,0,0,0,0,0,0,0,0,0,0\n";continue;}
    auto trajectory=manager.local_data_.position_traj_;double original=trajectory.getTimeSum();
    auto velocity=trajectory.getDerivative(),acceleration=velocity.getDerivative();
    double peak0=0,peak1=0;for(int i=0;i<=1000;++i)peak0=std::max(peak0,velocity.evaluateDeBoorT(original*i/1000).norm());
    double a0=acceleration.evaluateDeBoorT(0).norm(),a1=acceleration.evaluateDeBoorT(original).norm();
    auto jerk=acceleration.getDerivative();double j0=0,j1=0;
    for(int i=0;i<1000;++i)j0+=jerk.evaluateDeBoorT(original*(i+0.5)/1000).squaredNorm()/1000;
    auto begin=std::chrono::steady_clock::now();
    bool accepted=mode=="runtime"?(trajectory.getKnot().size()-trajectory.getControlPoint().cols()-1==5):
      cicc::improve(trajectory,manager.grid_map_,{0.3,0.5,4},true,true,mode!="v1",mode=="all");
    double millis=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-begin).count();
    velocity=trajectory.getDerivative();for(int i=0;i<=1000;++i)peak1=std::max(peak1,velocity.evaluateDeBoorT(trajectory.getTimeSum()*i/1000).norm());
    jerk=velocity.getDerivative().getDerivative();
    for(int i=0;i<1000;++i)j1+=jerk.evaluateDeBoorT(trajectory.getTimeSum()*(i+0.5)/1000).squaredNorm()/1000;
    out<<scene<<","<<d<<",1,"<<original<<","<<trajectory.getTimeSum()<<","<<accepted<<","<<peak0<<","<<peak1<<","<<a0<<","<<a1<<","<<millis<<","<<std::sqrt(j0)<<","<<std::sqrt(j1)<<"\n";
  }
}
