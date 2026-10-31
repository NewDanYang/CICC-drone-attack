#pragma once
#include <memory>
#include <vector>
#include <Eigen/Eigen>
class PlanningVisualization {public:using Ptr=std::shared_ptr<PlanningVisualization>;
  void displayInitPathList(const std::vector<Eigen::Vector3d>&,double,int){}
  void displayAStarList(const std::vector<std::vector<Eigen::Vector3d>>&,int){}
};
