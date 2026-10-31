#include "nodes/perception/multimodal_target_tracker.h"
#include <std_msgs/String.h>
#include <algorithm>
#include <atomic>

namespace { std::atomic<unsigned long> session_counter{0}; }

MultimodalTargetTracker::MultimodalTargetTracker(const std::string& name, const NodeConfig& config)
    : DroneActionNode(name, config) {
    auto nh=mct->getROSHandle();
    subscriber_=nh->subscribe("/multimodal/objects",1,&MultimodalTargetTracker::objectsCallback,this);
    gate_=nh->advertise<std_msgs::String>("/multimodal/balloon_target",2,true);
}

PortsList MultimodalTargetTracker::providedPorts() {
    return {InputPort<std::string>("object_name"),
            InputPort<double>("confidence_threshold",0.3,"Valid semantic observation threshold"),
            InputPort<int>("filter_window_size",3,"Pixel smoothing window"),
            OutputPort<PixelTarget>("pixel_target")};
}

void MultimodalTargetTracker::objectsCallback(const common_msgs::Objects::ConstPtr& msg) {
    std::lock_guard<std::mutex> lock(mutex_);
    objects_=*msg;
}

void MultimodalTargetTracker::publishGate(bool start) {
    std_msgs::String message;
    message.data="{\"action\":\""+std::string(start?"start":"stop")+"\",\"session\":\""+
        session_+"\",\"color\":\""+color_+"\"}";
    gate_.publish(message);
    ROS_INFO("MULTIMODAL_STAGE_%s session=%s color=%s",start?"START":"STOP",session_.c_str(),color_.c_str());
}

void MultimodalTargetTracker::invalid() {
    PixelTarget value;
    value.is_detected=false;
    value.timestamp=0.0;
    setOutput("pixel_target",value);
}

NodeStatus MultimodalTargetTracker::onStart() {
    target_=getInput<std::string>("object_name").value();
    color_=target_;
    const std::string suffix="_balloon";
    if(color_.size()>suffix.size() && color_.compare(color_.size()-suffix.size(),suffix.size(),suffix)==0)
        color_.erase(color_.size()-suffix.size());
    if(color_!="red" && color_!="purple" && color_!="blue") throw RuntimeError("Invalid FM9G color");
    threshold_=getInput<double>("confidence_threshold").value();
    window_=std::max(1,getInput<int>("filter_window_size").value());
    session_=std::to_string(ros::WallTime::now().toNSec())+"_"+std::to_string(++session_counter);
    history_.clear();last_sequence_=0;active_=true;
    {std::lock_guard<std::mutex> lock(mutex_);objects_=common_msgs::Objects();}
    invalid();publishGate(true);
    return NodeStatus::RUNNING;
}

NodeStatus MultimodalTargetTracker::onRunning() {
    common_msgs::Objects objects;
    {std::lock_guard<std::mutex> lock(mutex_);objects=objects_;}
    const std::string prefix="fm9g:"+session_+":";
    const double age=(ros::Time::now()-objects.header.stamp).toSec();
    if(objects.header.frame_id.compare(0,prefix.size(),prefix)!=0 || age< -0.05 || age>0.35) {
        history_.clear();invalid();return NodeStatus::RUNNING;
    }
    for(const auto& object:objects.objects) {
        if(object.class_name!=target_ || object.score<threshold_) continue;
        const double width=double(object.right_bottom_x)-object.left_top_x;
        const double height=double(object.right_bottom_y)-object.left_top_y;
        if(width<=0 || height<=0) continue;
        if(objects.header.seq!=last_sequence_) {
            history_.emplace_back(object.center_x,object.center_y,width,height,
                                  objects.header.stamp.toSec(),true);
            last_sequence_=objects.header.seq;
            while(int(history_.size())>window_) history_.pop_front();
        }
        double cx=0,cy=0,w=0,h=0;
        for(const auto& sample:history_) {cx+=sample.center_x;cy+=sample.center_y;w+=sample.width;h+=sample.height;}
        const double count=history_.size();
        if(count==0) {invalid();return NodeStatus::RUNNING;}
        PixelTarget value(cx/count,cy/count,w/count,h/count,objects.header.stamp.toSec(),true);
        setOutput("pixel_target",value);
        ROS_INFO_THROTTLE(0.2,"MULTIMODAL_PIXEL session=%s source=%s stamp=%.6f age=%.3f center=(%.1f,%.1f) size=(%.1f,%.1f)",
            session_.c_str(),objects.header.frame_id.c_str(),value.timestamp,age,value.center_x,value.center_y,value.width,value.height);
        return NodeStatus::RUNNING;
    }
    history_.clear();invalid();return NodeStatus::RUNNING;
}

void MultimodalTargetTracker::onHalted() {
    if(active_) {publishGate(false);active_=false;}
    history_.clear();invalid();
    // Preserve the original TargetTracker's inherited halt/hover behavior.
    DroneActionNode::onHalted();
}

BT_REGISTER_NODES(factory) {
    factory.registerNodeType<MultimodalTargetTracker>("MultimodalTargetTracker");
}
