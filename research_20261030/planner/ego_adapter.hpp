#pragma once
#include "certified_shortcut.hpp"
#include <bspline_opt/uniform_bspline.h>
#include <plan_env/grid_map.h>

namespace cicc {
inline V vectorOf(const Eigen::VectorXd &x){return {x[0],x[1],x[2]};}
inline Curve cubicPieces(ego_planner::UniformBspline spline){
  Curve result;result.family="control_polygon_shortcut";
  auto velocity=spline.getDerivative();auto knots=spline.getKnot();
  int count=spline.getControlPoint().cols(),degree=knots.size()-count-1;
  if(degree!=3)return result;
  double offset=knots[degree];
  for(int i=degree;i<count;++i){double left=knots[i]-offset,right=knots[i+1]-offset,t=right-left;
    if(t<=0)continue;
    V p0=vectorOf(spline.evaluateDeBoorT(left)),p1=vectorOf(spline.evaluateDeBoorT(right));
    V v0=vectorOf(velocity.evaluateDeBoorT(left)),v1=vectorOf(velocity.evaluateDeBoorT(right));
    std::array<V,6>a{};a[0]=p0;a[1]=mul(v0,t);
    a[2]=sub(mul(sub(p1,p0),3),mul(add(mul(v0,2),v1),t));
    a[3]=add(mul(sub(p0,p1),2),mul(add(v0,v1),t));
    result.segments.push_back({powerControls(a),t});}
  return result;
}
inline bool spatialShortcut(ego_planner::UniformBspline &best,State begin,State end,
                            Limits limits,const FreeBox&box,Budget&budget,
                            double max_jerk_mean_square=std::numeric_limits<double>::infinity()){
  auto points=best.getControlPoint();auto knots=best.getKnot();int n=points.cols();
  if(knots.size()-n-1!=3||n<8)return false;
  double dt=knots[4]-knots[3];
  for(int i=1;i<knots.size();++i)if(std::abs(knots[i]-knots[i-1]-dt)>1e-8)return false;
  double old=best.getTimeSum(),shortest=old;bool accepted=false;
  auto ev=[](V v){return Eigen::Vector3d(v[0],v[1],v[2]);};
  for(double alpha:{0.25,0.5,0.75,1.0})for(double scale:{0.70,0.80,0.90,0.95,0.98}){
    if(!budget.take())return accepted;
    if(old*scale>=shortest)continue;
    auto p=points;double interval=dt*scale;
    for(int i=3;i<n-3;++i){double f=double(i-1)/(n-3);
      Eigen::Vector3d chord=ev(add(mul(begin.p,1-f),mul(end.p,f)));
      p.col(i)=(1-alpha)*points.col(i)+alpha*chord;}
    p.col(1)=ev(sub(begin.p,mul(begin.a,interval*interval/6)));
    p.col(0)=p.col(1)-ev(mul(begin.v,interval))+ev(mul(begin.a,interval*interval/2));
    p.col(2)=p.col(1)+ev(mul(begin.v,interval))+ev(mul(begin.a,interval*interval/2));
    p.col(n-2)=ev(sub(end.p,mul(end.a,interval*interval/6)));
    p.col(n-3)=p.col(n-2)-ev(mul(end.v,interval))+ev(mul(end.a,interval*interval/2));
    p.col(n-1)=p.col(n-2)+ev(mul(end.v,interval))+ev(mul(end.a,interval*interval/2));
    ego_planner::UniformBspline candidate(p,3,interval);auto pieces=cubicPieces(candidate);
    if(jerkMeanSquare(pieces)<=max_jerk_mean_square&&endpointsMatch(pieces,begin,end)&&certify(pieces,limits,box,budget)){
      best=candidate;shortest=old*scale;accepted=true;}
  }
  return accepted;
}
inline bool improve(ego_planner::UniformBspline &original, GridMap::Ptr map,
                    Limits limits, bool enable_cruise, bool enable_quintic, bool enable_hermite=true,
                    bool enable_spatial=true, bool require_smoothness=true) {
  const double old_time=original.getTimeSum();
  auto velocity=original.getDerivative(),acceleration=velocity.getDerivative();
  State begin{vectorOf(original.evaluateDeBoorT(0)),vectorOf(velocity.evaluateDeBoorT(0)),
              vectorOf(acceleration.evaluateDeBoorT(0))};
  State end{vectorOf(original.evaluateDeBoorT(old_time)),vectorOf(velocity.evaluateDeBoorT(old_time)),
            vectorOf(acceleration.evaluateDeBoorT(old_time))};
  Budget budget;
  const double jerk_cap=require_smoothness?jerkMeanSquare(cubicPieces(original)):
    std::numeric_limits<double>::infinity();
  if(require_smoothness&&!std::isfinite(jerk_cap))return false;
  FreeBox free_box=[&](const V&lo,const V&hi){
    Eigen::Vector3d low(lo[0]-1e-9,lo[1]-1e-9,lo[2]-1e-9);
    Eigen::Vector3d high(hi[0]+1e-9,hi[1]+1e-9,hi[2]+1e-9);
    if(!map->isInMap(low)||!map->isInMap(high))return false;
    Eigen::Vector3i a,b;map->posToIndex(low,a);map->posToIndex(high,b);
    // Large boxes are subdivided before enumerating cells.
    double cells=double(b[0]-a[0]+1)*(b[1]-a[1]+1)*(b[2]-a[2]+1);
    if(cells>256)return false;
    for(int x=a[0];x<=b[0];++x)for(int y=a[1];y<=b[1];++y)for(int z=a[2];z<=b[2];++z){
      if(!budget.take())return false;
      Eigen::Vector3i id(x,y,z);Eigen::Vector3d center;
      if(!map->isInMap(id)||map->isUnknown(id))return false;
      map->indexToPos(id,center);
      if(map->getInflateOccupancy(center)!=0||map->getOccupancy(id)!=0)return false;
    }
    return true;
  };
  auto result=select(begin,end,old_time,limits,free_box,budget,enable_quintic,enable_cruise,enable_hermite,jerk_cap);
  auto spatial=original;
  if(enable_spatial&&spatialShortcut(spatial,begin,end,limits,free_box,budget,jerk_cap)&&
     (result.segments.empty()||spatial.getTimeSum()<result.duration())){
    original=spatial;
    ROS_INFO("[CertifiedShortcut] family=control_polygon_shortcut old_s=%.6f new_s=%.6f",old_time,original.getTimeSum());
    return true;
  }
  if(result.segments.empty())return false;
  Controls controls;std::vector<double> knots;
  if(!toBspline(result,controls,knots))return false;
  Eigen::MatrixXd points(3,controls.size());Eigen::VectorXd k(knots.size());
  for(size_t i=0;i<controls.size();++i)for(int j=0;j<3;++j)points(j,i)=controls[i][j];
  for(size_t i=0;i<knots.size();++i)k[i]=knots[i];
  ego_planner::UniformBspline candidate(points,5,result.duration());candidate.setKnot(k);
  original=candidate;
  ROS_INFO("[CertifiedShortcut] family=%s old_s=%.6f new_s=%.6f max_vel=%.6f max_acc=%.6f max_jerk=%.6f",
           result.family,old_time,result.duration(),limits.velocity,limits.acceleration,limits.jerk);
  return true;
}
} // namespace cicc
