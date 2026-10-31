#include "../planner/certified_shortcut.hpp"
#include <iostream>
#include <iomanip>
#include <random>
#include <stdexcept>
using namespace cicc;
int checks=0;
void require(bool condition,const char*label){++checks;if(!condition)throw std::runtime_error(label);}
Budget unlimited(){Budget b;b.wall_ms=0;b.remaining=1000000;return b;}
void verify(const Curve&c,State s,State e,Limits l){
  require(!c.segments.empty(),"empty candidate");require(endpointsMatch(c,s,e),"endpoint C2 mismatch");
  auto b=unlimited();require(certify(c,l,[](V,V){return true;},b),"continuous bound failure");
  for(auto &piece:c.segments){auto v=derivative(piece.p,piece.t),a=derivative(v,piece.t),j=derivative(a,piece.t);
    for(int i=0;i<=1000;++i){double t=i/1000.;
      require(norm(evaluate(v,t))<=l.velocity+1e-10,"sampled velocity");
      require(norm(evaluate(a,t))<=l.acceleration+1e-10,"sampled acceleration");
      require(norm(evaluate(j,t))<=l.jerk+1e-10,"sampled jerk");}}
  Controls p;std::vector<double>k;require(toBspline(c,p,k),"B-spline conversion");
  require(k.size()==p.size()+6,"B-spline dimensions");
}
int main(){try{
  Limits l{0.30,0.5,4.0};State s{{0,0,1},{0,0,0},{0,0,0}};
  auto free=[](V,V){return true;};
  std::cout<<std::setprecision(12)<<"{\"kind\":\"synthetic_selfcheck_not_flight\",\"straight_cases\":[";
  bool first=true;
  for(double d:{0.1,0.3,0.5,1.,2.,3.,5.}){
    State e{{d,0,1},{0,0,0},{0,0,0}};
    // Official global one-segment reference allocates 2*d/v. This is NOT
    // the complete EGO optimizer or a flight baseline.
    double reference=2*d/l.velocity;
    auto qbudget=unlimited(),cbudget=unlimited();
    auto q=select(s,e,reference,l,free,qbudget,true,false,false);
    auto c=select(s,e,reference,l,free,cbudget,false,true,false);
    if(!q.segments.empty())verify(q,s,e,l);
    if(!c.segments.empty())verify(c,s,e,l);
    if(!first)std::cout<<",";first=false;
    std::cout<<"{\"distance_m\":"<<d<<",\"global_reference_s\":"<<reference
      <<",\"quintic_s\":"<<(q.segments.empty()?0:q.duration())
      <<",\"cruise_s\":"<<(c.segments.empty()?0:c.duration())<<"}";
  }
  State e{{2,0,1},{0,0,0},{0,0,0}};
  auto c=cruise(s,e,l);verify(c,s,e,l);
  // Independent midpoint quadrature validates the exact jerk integral.
  double energy=0;
  for(auto&piece:c.segments){auto j=derivative(derivative(derivative(piece.p,piece.t),piece.t),piece.t);
    for(int i=0;i<10000;++i){double v=norm(evaluate(j,(i+0.5)/10000.));energy+=v*v*piece.t/10000;}}
  require(std::abs(jerkMeanSquare(c)-energy/c.duration())<1e-7,"jerk integral vs quadrature");
  auto smoothbudget=unlimited();
  require(select(s,e,20,l,free,smoothbudget,true,true,true,0).segments.empty(),"smoothness gate bypassed");
  require(!std::isfinite(jerkMeanSquare(Curve{})),"empty curve jerk accepted");
  auto obstacle=[](V lo,V hi){return hi[0]<0.9999||lo[0]>1.0001;};
  auto b=unlimited();require(!certify(c,l,obstacle,b),"thin obstacle accepted");
  b=unlimited();require(!certify(c,l,[](V,V){return false;},b),"unknown accepted");
  b=unlimited();require(!certify(c,{0,0.5,4},free,b),"zero limit accepted");
  b=unlimited();require(!certify(c,{NAN,0.5,4},free,b),"NaN limit accepted");
  b=unlimited();b.remaining=0;require(select(s,e,20,l,free,b).segments.empty(),"budget fallback");
  b=unlimited();auto invalid=s;invalid.p[0]=NAN;
  require(select(invalid,e,20,l,free,b).segments.empty(),"nonfinite state");
  b=unlimited();require(select(s,e,1,l,free,b).segments.empty(),"slower replacement");
  std::mt19937 rng(20261030);std::uniform_real_distribution<double>r(-1,1);
  int accepted=0;
  for(int i=0;i<100;++i){State a{{0,0,1},{r(rng)*0.08,r(rng)*0.08,0},{0,0,0}};
    State z{{1.5+r(rng),r(rng)*0.3,1},{r(rng)*0.08,r(rng)*0.08,0},{0,0,0}};
    auto budget=unlimited();auto result=select(a,z,20,l,free,budget);
    if(!result.segments.empty()){verify(result,a,z,l);++accepted;}}
  require(accepted>0,"no moving-state candidates");
  std::cout<<"],\"random_moving_cases\":100,\"random_accepted\":"<<accepted
    <<",\"checks\":"<<checks<<",\"passed\":true}\n";
  return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<"\n";return 1;}}
