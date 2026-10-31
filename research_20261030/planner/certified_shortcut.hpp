#pragma once
// Experimental trajectory generation. No ROS, world coordinates or speed overrides.
#include <array>
#include <vector>
#include <cmath>
#include <algorithm>
#include <limits>
#include <functional>
#include <chrono>

namespace cicc {
using V = std::array<double,3>;
inline V add(V a,V b){for(int k=0;k<3;++k)a[k]+=b[k];return a;}
inline V sub(V a,V b){for(int k=0;k<3;++k)a[k]-=b[k];return a;}
inline V mul(V a,double s){for(double &v:a)v*=s;return a;}
inline double norm(V a){return std::sqrt(a[0]*a[0]+a[1]*a[1]+a[2]*a[2]);}
inline bool finite(V a){return std::isfinite(a[0])&&std::isfinite(a[1])&&std::isfinite(a[2]);}
using Controls=std::vector<V>;
struct Segment {Controls p; double t;};
struct Curve {std::vector<Segment> segments; const char* family="none";
  double duration()const{double t=0;for(auto &s:segments)t+=s.t;return t;}};
struct State {V p,v,a;};
struct Limits {double velocity,acceleration,jerk;};
struct Budget {
  int remaining=50000;
  double wall_ms=3.0;
  std::chrono::steady_clock::time_point start=std::chrono::steady_clock::now();
  bool take(){return --remaining>=0 && (wall_ms<=0 ||
    std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count()<wall_ms);}
};
inline V evaluate(Controls p,double u){
  for(size_t n=p.size();n>1;--n)for(size_t i=0;i<n-1;++i)p[i]=add(mul(p[i],1-u),mul(p[i+1],u));
  return p.front();
}
inline Controls derivative(const Controls&p,double t){
  Controls d;for(size_t i=1;i<p.size();++i)d.push_back(mul(sub(p[i],p[i-1]),(p.size()-1)/t));return d;
}
inline std::pair<Controls,Controls> split(Controls p){
  Controls l(p.size()),r(p.size());
  for(size_t i=0;i<p.size();++i){l[i]=p.front();r[p.size()-1-i]=p[p.size()-1-i];
    for(size_t j=0;j<p.size()-1-i;++j)p[j]=mul(add(p[j],p[j+1]),0.5);}
  return {l,r};
}
inline bool bounded(const Controls&p,double cap,int depth,Budget &budget){
  if(!budget.take())return false;
  double maximum=0;for(auto v:p){if(!finite(v))return false;maximum=std::max(maximum,norm(v));}
  if(maximum<=cap)return true; // convex hull certificate for all times, not sampled maxima
  if(depth==0||norm(p.front())>cap||norm(p.back())>cap)return false;
  auto halves=split(p);return bounded(halves.first,cap,depth-1,budget)&&bounded(halves.second,cap,depth-1,budget);
}
using FreeBox=std::function<bool(const V&,const V&)>;
inline bool collisionFree(const Controls&p,const FreeBox&free_box,int depth,Budget &budget){
  if(!budget.take())return false;
  V lo=p.front(),hi=p.front();for(auto v:p){if(!finite(v))return false;
    for(int k=0;k<3;++k){lo[k]=std::min(lo[k],v[k]);hi[k]=std::max(hi[k],v[k]);}}
  if(free_box(lo,hi))return true;
  if(depth==0)return false;
  auto halves=split(p);
  return collisionFree(halves.first,free_box,depth-1,budget)&&collisionFree(halves.second,free_box,depth-1,budget);
}
inline bool certify(const Curve&c,Limits lim,const FreeBox&free_box,Budget&budget){
  if(c.segments.empty()||!std::isfinite(lim.velocity)||!std::isfinite(lim.acceleration)||
     !std::isfinite(lim.jerk)||lim.velocity<=0||lim.acceleration<=0||lim.jerk<=0)return false;
  for(auto&s:c.segments){
    if(!std::isfinite(s.t)||s.t<=0||s.p.size()!=6)return false;
    auto v=derivative(s.p,s.t),a=derivative(v,s.t),j=derivative(a,s.t);
    if(!bounded(v,lim.velocity,10,budget)||!bounded(a,lim.acceleration,10,budget)||
       !bounded(j,lim.jerk,10,budget)||!collisionFree(s.p,free_box,12,budget))return false;
  }
  for(size_t i=1;i<c.segments.size();++i){
    Controls l=c.segments[i-1].p,r=c.segments[i].p;
    for(int d=0;d<3;++d){if(norm(sub(l.back(),r.front()))>1e-8)return false;
      l=derivative(l,c.segments[i-1].t);r=derivative(r,c.segments[i].t);}
  }
  return true;
}
inline Curve quintic(State s,State e,double t){
  Controls p(6);p[0]=s.p;p[1]=add(s.p,mul(s.v,t/5));
  p[2]=add(sub(mul(p[1],2),p[0]),mul(s.a,t*t/20));
  p[5]=e.p;p[4]=sub(e.p,mul(e.v,t/5));
  p[3]=add(sub(mul(p[4],2),p[5]),mul(e.a,t*t/20));
  return {{{p,t}},"quintic_shortcut"};
}
inline double choose(int n,int k){double v=1;for(int i=1;i<=k;++i)v=v*(n-i+1)/i;return v;}
// Exact polynomial integral in Bernstein form (up to floating-point rounding).
// This is independent of sampling frequency and includes every time segment.
inline double jerkMeanSquare(const Curve&c){
  if(c.segments.empty())return std::numeric_limits<double>::infinity();
  double energy=0,time=0;
  for(const auto&s:c.segments){
    if(s.t<=0||!std::isfinite(s.t)||s.p.size()<4)return std::numeric_limits<double>::infinity();
    auto j=derivative(derivative(derivative(s.p,s.t),s.t),s.t);int n=int(j.size())-1;
    double integral=0;
    for(int a=0;a<=n;++a)for(int b=0;b<=n;++b){
      double dot=0;for(int k=0;k<3;++k)dot+=j[a][k]*j[b][k];
      integral+=dot*choose(n,a)*choose(n,b)/((2*n+1)*choose(2*n,a+b));
    }
    if(!std::isfinite(integral))return std::numeric_limits<double>::infinity();
    energy+=s.t*std::max(0.0,integral);time+=s.t;
  }
  return energy/time;
}
inline Controls powerControls(const std::array<V,6>&coeff){
  Controls p(6,V{0,0,0});for(int i=0;i<6;++i)for(int k=0;k<=i;++k)
    p[i]=add(p[i],mul(coeff[k],choose(i,k)/choose(5,k)));return p;
}
inline Curve cruise(State s,State e,Limits lim){
  Curve c;c.family="smooth_cruise";
  if(norm(s.v)>1e-10||norm(e.v)>1e-10||norm(s.a)>1e-10||norm(e.a)>1e-10)return c;
  double distance=norm(sub(e.p,s.p));if(distance<1e-6)return c;
  V unit=mul(sub(e.p,s.p),1/distance);
  // Keep a small numerical margin below ALL caps, never enlarge a tolerance.
  auto ramp=[&](double v){return std::max(1.5*v/(lim.acceleration*0.999),std::sqrt(6*v/(lim.jerk*0.999)));};
  double peak=lim.velocity*0.999;
  if(peak*ramp(peak)>distance){double lo=0,hi=peak;for(int i=0;i<60;++i){double mid=(lo+hi)/2;
    if(mid*ramp(mid)>distance)hi=mid;else lo=mid;}peak=lo;}
  double tr=ramp(peak),tc=std::max(0.0,distance/peak-tr);
  V scale=mul(unit,peak*tr);
  std::array<V,6> a{};a[0]=s.p;a[3]=scale;a[4]=mul(scale,-0.5);
  c.segments.push_back({powerControls(a),tr});
  V p=add(s.p,mul(scale,0.5));
  if(tc>1e-9){std::array<V,6> b{};b[0]=p;b[1]=mul(unit,peak*tc);
    c.segments.push_back({powerControls(b),tc});p=add(p,b[1]);}
  std::array<V,6> d{};d[0]=p;d[1]=scale;d[3]=mul(scale,-1);d[4]=mul(scale,0.5);
  c.segments.push_back({powerControls(d),tr});return c;
}
inline bool endpointsMatch(const Curve&c,State start,State end){
  if(c.segments.empty())return false;
  Controls a=c.segments.front().p,b=c.segments.back().p;
  V sa[]={start.p,start.v,start.a},sb[]={end.p,end.v,end.a};
  for(int i=0;i<3;++i){if(norm(sub(a.front(),sa[i]))>1e-8||norm(sub(b.back(),sb[i]))>1e-8)return false;
    a=derivative(a,c.segments.front().t);b=derivative(b,c.segments.back().t);}
  return true;
}
inline Segment velocityTransition(V p,V v0,V a0,V v1,V a1,double t){
  // Integrate a cubic Hermite velocity exactly to a quartic position curve.
  std::array<V,6> coeff{};coeff[0]=p;coeff[1]=mul(v0,t);coeff[2]=mul(a0,t*t/2);
  coeff[3]=mul(sub(mul(sub(v1,v0),3),mul(add(mul(a0,2),a1),t)),t/3);
  coeff[4]=mul(add(mul(sub(v0,v1),2),mul(add(a0,a1),t)),t/4);
  return {powerControls(coeff),t};
}
inline Curve hermiteCruise(State s,State e,double t,double ramp_fraction){
  double tr=t*ramp_fraction,tc=t-2*tr;
  Curve c;c.family="hermite_cruise";if(tr<=0||tc<=0)return c;
  // Solve the vector displacement constraint for the shared cruise velocity.
  V displacement=sub(e.p,s.p);
  V offset=add(mul(add(s.v,e.v),tr/2),mul(sub(s.a,e.a),tr*tr/12));
  V vc=mul(sub(displacement,offset),1/(tc+tr));
  auto first=velocityTransition(s.p,s.v,s.a,vc,{0,0,0},tr);
  std::array<V,6> mid{};mid[0]=first.p.back();mid[1]=mul(vc,tc);
  Segment middle{powerControls(mid),tc};
  auto last=velocityTransition(middle.p.back(),vc,{0,0,0},e.v,e.a,tr);
  c.segments={first,middle,last};return c;
}
inline Curve select(State s,State e,double original_duration,Limits lim,const FreeBox&box,Budget&budget,
                    bool use_quintic=true,bool use_cruise=true,bool use_hermite=true,
                    double max_jerk_mean_square=std::numeric_limits<double>::infinity()){
  Curve best;
  if(!finite(s.p)||!finite(s.v)||!finite(s.a)||!finite(e.p)||!finite(e.v)||!finite(e.a)||
     !std::isfinite(original_duration)||original_duration<=0||
     !std::isfinite(lim.velocity)||!std::isfinite(lim.acceleration)||!std::isfinite(lim.jerk)||
     lim.velocity<=0||lim.acceleration<=0||lim.jerk<=0)return best;
  double upper=original_duration*0.95,lower=norm(sub(e.p,s.p))/lim.velocity;
  if(use_cruise){auto c=cruise(s,e,lim);
    if(!c.segments.empty()&&c.duration()<upper&&jerkMeanSquare(c)<=max_jerk_mean_square&&endpointsMatch(c,s,e)&&certify(c,lim,box,budget)){
      best=c;upper=c.duration();}}
  if(use_quintic&&lower<upper){
    for(int i=0;i<=24&&budget.take();++i){double t=lower+(upper-lower)*i/24.0;
      auto c=quintic(s,e,t);if(t>0&&jerkMeanSquare(c)<=max_jerk_mean_square&&endpointsMatch(c,s,e)&&certify(c,lim,box,budget)){
        best=c;break;}}
  }
  // A separate candidate family, preserving arbitrary endpoint p/v/a. Its
  // modest 2% adoption gate is explicit; it does not alter any dynamic limit.
  if(use_hermite){
    double max_time=best.segments.empty()?original_duration*0.98:best.duration();
    for(int i=1;i<=16&&lower<max_time&&budget.take();++i){
      double t=lower+(max_time-lower)*i/16.;
      for(double f:{0.03,0.05,0.06,0.065,0.07,0.075,0.08,0.085,0.09,0.095,0.10,0.11,0.125,0.15,0.20,0.25,0.33,0.45}){
        auto c=hermiteCruise(s,e,t,f);
        if(jerkMeanSquare(c)<=max_jerk_mean_square&&endpointsMatch(c,s,e)&&certify(c,lim,box,budget)){
          best=c;return best;}
      }
    }
  }
  return best;
}
inline V curveValue(const Curve&c,double t){
  for(auto&s:c.segments){if(t<=s.t)return evaluate(s.p,std::max(0.0,t/s.t));t-=s.t;}
  return c.segments.back().p.back();
}
inline double basis(int i,int degree,double t,const std::vector<double>&k){
  if(degree==0)return k[i]<=t&&t<k[i+1]?1.0:0.0;
  double out=0,a=k[i+degree]-k[i],b=k[i+degree+1]-k[i+1];
  if(a>0)out+=(t-k[i])/a*basis(i,degree-1,t,k);
  if(b>0)out+=(k[i+degree+1]-t)/b*basis(i+1,degree-1,t,k);return out;
}
// C2 joins require interior multiplicity THREE. Multiplicity five would cause
// 0/0 in the upstream second derivative, despite matching Bezier derivatives.
// Recover the unique equivalent spline by Greville collocation with pivoting.
inline bool toBspline(const Curve&c,Controls&points,std::vector<double>&knots){
  if(c.segments.empty())return false;
  points.clear();knots.assign(6,0.0);double time=0;
  for(size_t i=0;i<c.segments.size();++i){time+=c.segments[i].t;
    knots.insert(knots.end(),i+1==c.segments.size()?6:3,time);}
  const int n=int(knots.size())-6;
  std::vector<std::vector<double>> matrix(n,std::vector<double>(n+3,0));
  for(int row=0;row<n;++row){double t=0;for(int j=1;j<=5;++j)t+=knots[row+j]/5;
    V target=curveValue(c,t);
    if(row==n-1)matrix[row][n-1]=1;
    else for(int col=0;col<n;++col)matrix[row][col]=basis(col,5,t,knots);
    for(int j=0;j<3;++j)matrix[row][n+j]=target[j];}
  for(int col=0;col<n;++col){int pivot=col;
    for(int r=col+1;r<n;++r)if(std::abs(matrix[r][col])>std::abs(matrix[pivot][col]))pivot=r;
    if(std::abs(matrix[pivot][col])<1e-12)return false;
    std::swap(matrix[pivot],matrix[col]);double scale=matrix[col][col];
    for(int j=col;j<n+3;++j)matrix[col][j]/=scale;
    for(int r=0;r<n;++r)if(r!=col){double f=matrix[r][col];
      for(int j=col;j<n+3;++j)matrix[r][j]-=f*matrix[col][j];}}
  for(int i=0;i<n;++i)points.push_back({matrix[i][n],matrix[i][n+1],matrix[i][n+2]});
  for(int j=0;j<100;++j){double t=time*j/100;V value{0,0,0};
    for(int i=0;i<n;++i)value=add(value,mul(points[i],basis(i,5,t,knots)));
    if(!finite(value)||norm(sub(value,curveValue(c,t)))>1e-8)return false;}
  return true;
}
} // namespace cicc
