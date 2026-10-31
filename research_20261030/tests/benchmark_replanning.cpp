// Offline synthetic states; NOT recorded flight states or ROS execution.
#include <plan_manage/planner_manager.h>
#include "../planner/ego_adapter.hpp"
#include <fstream>
#include <iomanip>
#include <cstdlib>
#include <stdexcept>
using namespace ego_planner;
double sampledJerk(UniformBspline trajectory){
  auto j=trajectory.getDerivative().getDerivative().getDerivative();double sum=0;
  for(int i=0;i<10000;++i)sum+=j.evaluateDeBoorT(trajectory.getTimeSum()*(i+0.5)/10000).squaredNorm()/10000;
  return std::sqrt(sum);
}
double exactJerk(UniformBspline trajectory){
  // Independent Gauss-Legendre integration: norm-squared jerk is at most
  // quartic on each knot span for degree <= 5; three nodes integrate exactly.
  auto knots=trajectory.getKnot();int count=trajectory.getControlPoint().cols();
  int degree=knots.size()-count-1;
  if(degree<3||degree>5)throw std::runtime_error("unsupported test degree");
  auto jerk=trajectory.getDerivative().getDerivative().getDerivative();double energy=0;
  const double nodes[]={-std::sqrt(3./5),0,std::sqrt(3./5)},weights[]={5./9,8./9,5./9};
  for(int i=degree;i<count;++i){double h=(knots[i+1]-knots[i])/2,mid=(knots[i+1]+knots[i])/2-knots[degree];
    if(h<=0)continue;
    for(int q=0;q<3;++q)energy+=h*weights[q]*jerk.evaluateDeBoorT(mid+h*nodes[q]).squaredNorm();
  }
  return std::sqrt(energy/trajectory.getTimeSum());
}
int main(int argc,char**argv){
  if(argc<2||argc>3)return 2;bool runtime=argc==3&&std::string(argv[2])=="runtime";
  std::ofstream out(argv[1]);out<<std::setprecision(12);
  out<<"case,map,profile,distance,success,original_s,original_jerk_exact,original_jerk_sampled,ungated_accepted,ungated_s,ungated_jerk_sampled,guarded_accepted,guarded_s,guarded_jerk_sampled,guarded_ms,guarded_peak_velocity\n";
  int id=0;
  for(int scene=0;scene<3;++scene)for(int profile=0;profile<5;++profile)for(double d:{0.75,1.5,2.5,3.5}){
    ros::NodeHandle nh;nh.params={{"manager/max_vel",0.3},{"manager/max_acc",0.5},{"manager/max_jerk",4},
      {"manager/control_points_distance",0.1},{"manager/feasibility_tolerance",0.05},{"manager/planning_horizon",5},
      {"optimization/lambda_smooth",1},{"optimization/lambda_collision",5},{"optimization/lambda_feasibility",0.1},
      {"optimization/lambda_fitness",1},{"optimization/dist0",0.1},{"optimization/max_vel",0.3},{"optimization/max_acc",0.5}};
    if(runtime)nh.params["manager/certified_shortcut"]=1;
    EGOPlannerManager manager;manager.initPlanModules(nh,std::make_shared<PlanningVisualization>());
    manager.grid_map_->unknown=scene==2;
    if(scene==1)manager.grid_map_->obstacles.push_back({{d/2-0.12,-0.25,0.6},{d/2+0.12,0.25,1.4}});
    Eigen::Vector3d v=Eigen::Vector3d::Zero(),a=v,endv=v;
    if(profile==1)v[0]=0.15;
    if(profile==2)v[0]=0.27;
    if(profile==3)v[1]=0.15;
    if(profile==4){v={0.10,0.10,0};a={0.03,-0.03,0};endv={0.15,0,0};}
    std::srand(20261031+id);
    bool ok=manager.reboundReplan({0,0,1},v,a,{d,0,1},endv,true,false);
    out<<id++<<","<<scene<<","<<profile<<","<<d<<","<<ok;
    if(!ok){out<<",0,0,0,0,0,0,0,0,0,0,0\n";continue;}
    auto original=manager.local_data_.position_traj_,ungated=original,guarded=original;
    bool u=!runtime&&cicc::improve(ungated,manager.grid_map_,{0.3,0.5,4},true,true,true,true,false);
    auto begin=std::chrono::steady_clock::now();
    bool g=!runtime&&cicc::improve(guarded,manager.grid_map_,{0.3,0.5,4},true,true,true,true,true);
    double millis=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-begin).count();
    auto gv=guarded.getDerivative();double peak=0;
    for(int i=0;i<=10000;++i)peak=std::max(peak,gv.evaluateDeBoorT(guarded.getTimeSum()*i/10000).norm());
    if(!runtime&&std::abs(exactJerk(original)-std::sqrt(cicc::jerkMeanSquare(cicc::cubicPieces(original))))>1e-9)
      throw std::runtime_error("independent jerk integration disagreement");
    if(g){
      auto ga=gv.getDerivative(),gj=ga.getDerivative();
      if(scene==2||peak>0.3+1e-10||guarded.getTimeSum()>original.getTimeSum()*0.98+1e-8)
        throw std::runtime_error("acceptance invariant");
      auto left=original,right=guarded;
      for(int order=0;order<3;++order){
        for(int endpoint=0;endpoint<2;++endpoint)
          if((left.evaluateDeBoorT(endpoint*original.getTimeSum())-
              right.evaluateDeBoorT(endpoint*guarded.getTimeSum())).norm()>1e-8)
            throw std::runtime_error("endpoint continuity");
        left=left.getDerivative();right=right.getDerivative();
      }
      for(int i=0;i<=10000;++i){double t=guarded.getTimeSum()*i/10000;
        if(ga.evaluateDeBoorT(t).norm()>0.5+1e-8||gj.evaluateDeBoorT(t).norm()>4+1e-8||
           manager.grid_map_->getInflateOccupancy(guarded.evaluateDeBoorT(t))!=0)
          throw std::runtime_error("sampled dynamics/collision");
      }
      if(exactJerk(guarded)>exactJerk(original)+1e-10)
        throw std::runtime_error("jerk regression");
    }
    out<<","<<original.getTimeSum()<<","<<exactJerk(original)
       <<","<<sampledJerk(original)<<","<<u<<","<<ungated.getTimeSum()<<","<<sampledJerk(ungated)
       <<","<<g<<","<<guarded.getTimeSum()<<","<<sampledJerk(guarded)<<","<<millis<<","<<peak<<"\n";
  }
}
