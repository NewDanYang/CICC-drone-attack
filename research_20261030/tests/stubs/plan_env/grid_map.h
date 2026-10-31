#pragma once
// Synthetic, already-inflated voxel boxes. NO claim of real sensor simulation.
#include <Eigen/Eigen>
#include <memory>
#include <vector>
#include <ros/ros.h>
class GridMap {public:using Ptr=std::shared_ptr<GridMap>;
  struct Box {Eigen::Vector3d lo,hi;};std::vector<Box> obstacles;
  bool unknown=false;
  void initMap(ros::NodeHandle&){}
  double getResolution(){return 0.05;}
  bool isInMap(const Eigen::Vector3d&p){return p.allFinite()&&p[0]>-5&&p[0]<5&&p[1]>-5&&p[1]<5&&p[2]>0&&p[2]<3;}
  bool isInMap(const Eigen::Vector3i&i){return (i.array()>=0).all()&&i[0]<200&&i[1]<200&&i[2]<60;}
  void posToIndex(const Eigen::Vector3d&p,Eigen::Vector3i&i){i=((p-Eigen::Vector3d(-5,-5,0))/0.05).array().floor().cast<int>();}
  void indexToPos(const Eigen::Vector3i&i,Eigen::Vector3d&p){p=Eigen::Vector3d(-5,-5,0)+(i.cast<double>()+Eigen::Vector3d::Constant(0.5))*0.05;}
  bool isUnknown(const Eigen::Vector3i&){return unknown;}
  int getInflateOccupancy(const Eigen::Vector3d&p){if(!isInMap(p))return -1;
    for(auto&b:obstacles)if((p.array()>=b.lo.array()).all()&&(p.array()<=b.hi.array()).all())return 1;return 0;}
  int getOccupancy(const Eigen::Vector3i&i){Eigen::Vector3d p;indexToPos(i,p);return getInflateOccupancy(p);}
};
