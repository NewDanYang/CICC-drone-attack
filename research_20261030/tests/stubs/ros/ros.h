#pragma once
// Only for ROS-free compilation of the unchanged upstream spline implementation.
#include <vector>
#include <memory>
#include <map>
#include <string>
#include <chrono>
#define ROS_INFO(...) do {} while (0)
#define ROS_WARN(...) do {} while (0)
#define ROS_ERROR(...) do {} while (0)
namespace ros {
struct Duration {double value=0;Duration(){}Duration(double v):value(v){}double toSec()const{return value;}};
inline Duration operator+(Duration a,Duration b){return Duration(a.value+b.value);}
struct Time {double value=0;Time(){}Time(double v):value(v){}
  static Time now(){return Time(std::chrono::duration<double>(std::chrono::steady_clock::now().time_since_epoch()).count());}
  double toSec()const{return value;}};
inline Duration operator-(Time a,Time b){return Duration(a.value-b.value);}
class NodeHandle {public:std::map<std::string,double> params;
  template<class T>void param(const std::string&key,T&out,T fallback){auto it=params.find(key);out=it==params.end()?fallback:T(it->second);}};
}
