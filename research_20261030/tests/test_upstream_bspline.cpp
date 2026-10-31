#include <vector>
#include "../planner/certified_shortcut.hpp"
#include <bspline_opt/uniform_bspline.h>
#include <iostream>
#include <stdexcept>
using namespace cicc;
int main(){try{
  int checked=0;double maximum=0;
  for(double distance:{0.1,0.3,0.5,1.,2.,3.,5.}){
    State s{{0,0,1},{0,0,0},{0,0,0}},e{{distance,0,1},{0,0,0},{0,0,0}};
    State moving_s=s,moving_e=e;moving_s.v={0.03,0.01,0};moving_s.a={0.01,0,0};
    moving_e.v={0.02,-0.01,0};moving_e.a={-0.03,0,0};
    for(auto curve:{cruise(s,e,{0.3,0.5,4}),quintic(s,e,2*distance/0.3),
                   hermiteCruise(moving_s,moving_e,2*distance/0.3,0.15)}){
      Controls points;std::vector<double>knots;
      if(!toBspline(curve,points,knots))throw std::runtime_error("conversion");
      Eigen::MatrixXd p(3,points.size());Eigen::VectorXd k(knots.size());
      for(size_t i=0;i<points.size();++i)for(int j=0;j<3;++j)p(j,i)=points[i][j];
      for(size_t i=0;i<knots.size();++i)k[i]=knots[i];
      ego_planner::UniformBspline upstream(p,5,1);upstream.setKnot(k);
      auto velocity=upstream.getDerivative(),acceleration=velocity.getDerivative(),jerk=acceleration.getDerivative();
      double offset=0;
      for(auto&segment:curve.segments){
        auto v=derivative(segment.p,segment.t),a=derivative(v,segment.t),j=derivative(a,segment.t);
        for(int i=0;i<=1000;++i){double u=i/1000.,t=offset+u*segment.t;
          std::vector<Eigen::VectorXd>actual={upstream.evaluateDeBoorT(t),velocity.evaluateDeBoorT(t),acceleration.evaluateDeBoorT(t)};
          std::vector<V>expected={evaluate(segment.p,u),evaluate(v,u),evaluate(a,u)};
          for(int d=0;d<3;++d){double err=norm(sub({actual[d][0],actual[d][1],actual[d][2]},expected[d]));
            if(!actual[d].allFinite()||err>1e-7)throw std::runtime_error("upstream p/v/a mismatch or NaN");
            maximum=std::max(maximum,err);++checked;}
          // Jerk may jump at a C2 join; compare strictly inside each segment.
          if(i>0&&i<1000){auto value=jerk.evaluateDeBoorT(t);
            if(!value.allFinite()||norm(sub({value[0],value[1],value[2]},evaluate(j,u)))>1e-7)
              throw std::runtime_error("upstream jerk mismatch or NaN");++checked;}
        }offset+=segment.t;
      }
    }
  }
  std::cout<<"{\"upstream_bspline_checks\":"<<checked<<",\"max_pva_error\":"<<maximum<<",\"passed\":true}\n";
  return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<"\n";return 1;}}
