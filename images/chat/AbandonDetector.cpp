#include "AbandonDetector.h"
#include "NotificationManager.h" // Nhúng Manager để gọi HTTP POST
#include <iostream>
#include <fstream>
#include <chrono>
#include <iomanip>
#include <cmath>
#include <cstdlib>

extern const std::vector<std::string> CLASSES;
extern const std::map<int, float> REAL_HEIGHTS;

AbandonDetector::AbandonDetector(DistanceEstimator& estimator) : dist_est(estimator) {
    // Không cần mkdir ở đây vì NotificationManager đã tự xử lý thư mục image/
}

std::string AbandonDetector::getISOTime() {
    auto now = std::chrono::system_clock::now();
    auto itt = std::chrono::system_clock::to_time_t(now);
    std::ostringstream ss;
    ss << std::put_time(gmtime(&itt), "%Y-%m-%dT%H:%M:%S") << ".000Z";
    return ss.str();
}

// CẬP NHẬT: Trích xuất thêm độ tin cậy (confidence) thực tế
int AbandonDetector::getBestClass(const std::vector<float>& tlbr, const std::vector<Detection>& results, float& out_conf) {
    if (results.empty()) {
        out_conf = 0.0f;
        return 0;
    }
    float tx_center = (tlbr[0] + tlbr[2]) / 2.0f;
    float ty_center = (tlbr[1] + tlbr[3]) / 2.0f;
    int best_class = 0; 
    float min_dist = 1e18f;
    out_conf = 0.0f;

    for (const auto& res : results) {
        float rx = res.x + res.w / 2.0f, ry = res.y + res.h / 2.0f;
        float dist = (tx_center - rx) * (tx_center - rx) + (ty_center - ry) * (ty_center - ry);
        if (dist < min_dist) { 
            min_dist = dist; 
            best_class = res.class_id; 
            out_conf = res.conf; // Lấy confidence thực tế từ YOLO
        }
    }
    return best_class;
}

ObjectState* AbandonDetector::getNearestHuman(float x_3d, float z_3d, float& out_dist) {
    float min_dist = 99.0f;
    ObjectState* nearest_human = nullptr;
    
    for (auto& human : current_humans) {
        float dist = std::sqrt(std::pow(x_3d - human.x_3d, 2) + std::pow(z_3d - human.z_3d, 2));
        if (dist < min_dist) { 
            min_dist = dist; 
            nearest_human = &human;
        }
    }
    out_dist = min_dist;
    return nearest_human;
}

void AbandonDetector::processFrame(cv::Mat& frame, const std::vector<STrack>& tracks, const std::vector<Detection>& results, float delta_t) {
    std::vector<int> current_track_ids;
    current_humans.clear();

    // BƯỚC 1: Lọc dữ liệu 3D và Smooth
    for (const auto& track : tracks) {
        if (!track.is_activated) continue;
        int tid = track.track_id;
        current_track_ids.push_back(tid);

        // Lấy class_id và confidence hiện tại
        float current_conf = 0.0f;
        int class_id = getBestClass(track.tlbr, results, current_conf);
        
        cv::Rect bbox((int)track.tlbr[0], (int)track.tlbr[1], (int)(track.tlbr[2] - track.tlbr[0]), (int)(track.tlbr[3] - track.tlbr[1]));
        
        if (memory.find(tid) == memory.end()) {
            ObjectState new_obj;
            new_obj.track_id = tid;
            new_obj.class_id = class_id;
            new_obj.label = (class_id < (int)CLASSES.size()) ? CLASSES[class_id] : "Unknown";
            new_obj.status = ObjectStatus::NEW;
            new_obj.first_seen_iso = getISOTime();
            new_obj.alert_sent = false;
            new_obj.bbox = bbox;
            new_obj.confidence = current_conf; // Gán confidence khởi tạo
            memory[tid] = new_obj;
        }

        ObjectState& obj = memory[tid];
        obj.bbox = bbox;
        obj.time_since_last_seen = 0.0f;
        obj.hit_streak++;

        // Cập nhật confidence cao nhất nếu model nhìn rõ hơn ở các frame sau
        if (current_conf > obj.confidence) {
            obj.confidence = current_conf;
        }

        float aspect_ratio = (float)bbox.height / (float)bbox.width;
        bool is_occluded = (class_id == 3 && aspect_ratio < 1.1f);
        float v_max_raw = (class_id == 3) ? (bbox.y + bbox.height * 0.93f) : (bbox.y + bbox.height * 0.96f);

        if (obj.smoothed_vmax < 0) obj.smoothed_vmax = v_max_raw;
        else obj.smoothed_vmax = ALPHA_VMAX * v_max_raw + (1.0f - ALPHA_VMAX) * obj.smoothed_vmax;

        float real_h = REAL_HEIGHTS.count(class_id) ? REAL_HEIGHTS.at(class_id) : 0.5f;
        int u_center = bbox.x + bbox.width / 2;
        
        WorldPoint wp = dist_est.calculateHybridDistance(u_center, (int)obj.smoothed_vmax, bbox.height, class_id, real_h, frame.rows, is_occluded);
        
        if (wp.z < 99.0f) {
            if (obj.smoothed_z < 0) obj.smoothed_z = wp.z;
            else obj.smoothed_z = ALPHA_DIST * wp.z + (1.0f - ALPHA_DIST) * obj.smoothed_z;
            obj.z_3d = obj.smoothed_z;
            obj.x_3d = wp.x;
        }

        if (class_id == 3) {
            current_humans.push_back(obj);
            drawObject(frame, obj);
        }
    }

    // BƯỚC 2: Timeout Xóa Bộ Nhớ
    for (auto it = memory.begin(); it != memory.end(); ) {
        if (std::find(current_track_ids.begin(), current_track_ids.end(), it->first) == current_track_ids.end()) {
            it->second.time_since_last_seen += delta_t;
            it->second.hit_streak = 0;
            if (it->second.time_since_last_seen > LOST_TIMEOUT) {
                it = memory.erase(it);
                continue;
            }
        }
        ++it;
    }

    // BƯỚC 3: Logic Máy Trạng Thái FSM & Gọi NotificationManager
    for (auto& pair : memory) {
        ObjectState& obj = pair.second;
        if (obj.class_id == 3 || obj.status == ObjectStatus::SAFE) {
            if (obj.class_id != 3) drawObject(frame, obj);
            continue;
        }

        if (obj.status == ObjectStatus::NEW) {
            if (obj.hit_streak >= CONFIRM_FRAMES) obj.status = ObjectStatus::TRACKING;
            else continue;
        }

        obj.T_life += delta_t;
        
        float nearest_dist = 99.0f;
        ObjectState* nearest_human = getNearestHuman(obj.x_3d, obj.z_3d, nearest_dist);

        // Vẽ tia nối
        if (nearest_human != nullptr && nearest_dist < 4.0f) {
            int obj_u = obj.bbox.x + obj.bbox.width / 2;
            int obj_v = obj.bbox.y + obj.bbox.height;
            int hum_u = nearest_human->bbox.x + nearest_human->bbox.width / 2;
            int hum_v = nearest_human->bbox.y + nearest_human->bbox.height; 

            cv::Scalar lineColor = (nearest_dist <= DIST_ZONE) ? cv::Scalar(255, 0, 255) : cv::Scalar(0, 165, 255); 
            cv::line(frame, cv::Point(obj_u, obj_v), cv::Point(hum_u, hum_v), lineColor, 2);
            
            int mid_u = (obj_u + hum_u) / 2;
            int mid_v = (obj_v + hum_v) / 2;
            std::string dist_text = cv::format("%.2fm", nearest_dist);
            
            cv::putText(frame, dist_text, cv::Point(mid_u, mid_v - 10), cv::FONT_HERSHEY_SIMPLEX, 0.6, cv::Scalar(0, 0, 0), 3);
            cv::putText(frame, dist_text, cv::Point(mid_u, mid_v - 10), cv::FONT_HERSHEY_SIMPLEX, 0.6, lineColor, 2);
        }

        // Kiểm tra vùng an toàn
        if (nearest_dist <= DIST_ZONE) {
            obj.T_human += delta_t;
            if (obj.T_human >= T_SAFE_NEARBY && obj.status != ObjectStatus::ALERT) {
                obj.status = ObjectStatus::SAFE; 
            }
        } else {
            obj.T_human = 0.0f; 
            obj.T_alone += delta_t;

            // Xử lý chuyển trạng thái
            if (obj.status == ObjectStatus::TRACKING && obj.T_alone >= T_SUSPICIOUS) {
                obj.status = ObjectStatus::SUSPICIOUS;
            } else if (obj.status == ObjectStatus::SUSPICIOUS && obj.T_alone >= T_ALERT) {
                obj.status = ObjectStatus::ALERT;
                obj.T_alone = 0; // Bắt đầu đếm thời gian Monitor
                
                // =========================================================
                // GỌI HÀM TỪ NOTIFICATION MANAGER KÈM CONFIDENCE THỰC TẾ
                // =========================================================
                if (!obj.alert_sent) {
                    std::string last_seen_iso = getISOTime();
                    
                    NotificationManager::sendAlert(
                        obj.label,                  
                        obj.confidence,             // TRUYỀN CONFIDENCE THỰC TẾ VÀO ĐÂY
                        obj.x_3d,                   
                        obj.z_3d,                   
                        obj.first_seen_iso,         
                        last_seen_iso,              
                        (int)(T_ALERT),             
                        frame                       
                    );

                    obj.alert_sent = true;
                }
                // =========================================================

            } else if (obj.status == ObjectStatus::ALERT) {
                obj.status = ObjectStatus::MONITOR;
            } else if (obj.status == ObjectStatus::MONITOR) {
                if (obj.T_alone >= T_MONITOR_END) {
                    obj.status = ObjectStatus::SAFE; 
                    obj.T_alone = 0; 
                }
            }
        }

        // BƯỚC 4: Vẽ Box Đồ vật
        drawObject(frame, obj);
    }
}

ObjectStatus AbandonDetector::getHighestPriorityStatus() const {
    ObjectStatus highest = ObjectStatus::SAFE;
    int max_priority = -1;

    for (const auto& pair : memory) {
        if (pair.second.class_id == 3) continue; // Bỏ qua class người

        int priority = 0;
        switch(pair.second.status) {
            case ObjectStatus::ALERT:
            case ObjectStatus::MONITOR: priority = 4; break;
            case ObjectStatus::SUSPICIOUS: priority = 3; break;
            case ObjectStatus::TRACKING: priority = 2; break;
            case ObjectStatus::SAFE:
            case ObjectStatus::NEW: priority = 0; break;
        }

        if (priority > max_priority) {
            max_priority = priority;
            highest = pair.second.status;
        }
    }
    return highest;
}

void AbandonDetector::drawObject(cv::Mat& frame, const ObjectState& obj) {
    if (obj.time_since_last_seen > 0.0f) return;

    cv::Scalar color;
    std::string state_str = "";
    
    switch (obj.status) {
        case ObjectStatus::NEW: color = cv::Scalar(200, 200, 200); state_str = "WAIT"; break;
        case ObjectStatus::TRACKING: color = cv::Scalar(0, 255, 0); state_str = "TRACK"; break;
        case ObjectStatus::SUSPICIOUS: color = cv::Scalar(0, 165, 255); state_str = "SUSP"; break;
        case ObjectStatus::ALERT: 
        case ObjectStatus::MONITOR: color = cv::Scalar(0, 0, 255); state_str = "ALERT!"; 
            cv::putText(frame, "WARNING: ITEM ABANDONED!", cv::Point(50, 50), cv::FONT_HERSHEY_SIMPLEX, 1.2, cv::Scalar(0, 0, 255), 3);
            break;
        case ObjectStatus::SAFE: color = cv::Scalar(255, 0, 0); state_str = "SAFE"; break;
    }

    if (obj.class_id == 3) color = cv::Scalar(255, 255, 0); 

    cv::rectangle(frame, obj.bbox, color, 2);
    
    std::string label;
    if (obj.class_id != 3) {
        // CẬP NHẬT: Hiển thị thêm chỉ số confidence [%.2f] trên màn hình camera
        label = cv::format("ID:%d %s [%.2f] [%.1fm] %s (T:%.0f)", obj.track_id, obj.label.c_str(), obj.confidence, obj.z_3d, state_str.c_str(), obj.T_alone);
    } else {
        label = cv::format("ID:%d %s [%.1fm]", obj.track_id, obj.label.c_str(), obj.z_3d);
    }
    
    int baseLine;
    cv::Size labelSize = cv::getTextSize(label, cv::FONT_HERSHEY_SIMPLEX, 0.5, 1, &baseLine);
    cv::rectangle(frame, cv::Rect(obj.bbox.x, obj.bbox.y - labelSize.height - 5, labelSize.width, labelSize.height + 5), color, cv::FILLED);
    cv::putText(frame, label, cv::Point(obj.bbox.x, obj.bbox.y - 2), cv::FONT_HERSHEY_SIMPLEX, 0.5, cv::Scalar(0, 0, 0), 1);
}
