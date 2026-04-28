#ifndef ABANDON_DETECTOR_H
#define ABANDON_DETECTOR_H

#include <map>
#include <vector>
#include <string>
#include <opencv2/opencv.hpp>
#include "Config.h"
#include "BYTETracker.h"
#include "DistanceEstimator.h"

class AbandonDetector {
private:
    std::map<int, ObjectState> memory;
    DistanceEstimator& dist_est;

    const float DIST_ZONE = 1.5f;       
    const float T_SAFE_NEARBY = 30.0f;  
    const float T_SUSPICIOUS = 60.0f;   
    const float T_ALERT = 120.0f;       
    const float T_MONITOR_END = 15.0f;  
    const float LOST_TIMEOUT = 2.0f;    
    const int CONFIRM_FRAMES = 5;       

    // Bổ sung lại 2 hằng số lọc nhiễu bị thiếu
    const float ALPHA_VMAX = 0.45f;
    const float ALPHA_DIST = 0.20f;

    std::vector<ObjectState> current_humans; 

public:
    AbandonDetector(DistanceEstimator& estimator);
    void processFrame(cv::Mat& frame, const std::vector<STrack>& tracks, const std::vector<Detection>& results, float delta_t);
    ObjectStatus getHighestPriorityStatus() const;

private:
    int getBestClass(const std::vector<float>& tlbr, const std::vector<Detection>& results, float &out_conf);
    ObjectState* getNearestHuman(float x_3d, float z_3d, float& out_dist);
    void drawObject(cv::Mat& frame, const ObjectState& obj);
    std::string getISOTime(); 
};

#endif
