package com.example.nfcemployeewelcome.model;

import com.google.gson.annotations.SerializedName;

/**
 * Mirrors backend schema IdentifyResponse:
 * {"success": true, "message": "...", "employee_id": "EMP001", "employee_name": "Gaurav Patil"}
 */
public class IdentifyResponse {

    @SerializedName("success")
    private boolean success;

    @SerializedName("message")
    private String message;

    @SerializedName("employee_id")
    private String employeeId;

    @SerializedName("employee_name")
    private String employeeName;

    @SerializedName("photo_url")
    private String photoUrl;

    public boolean isSuccess() {
        return success;
    }

    public String getMessage() {
        return message;
    }

    public String getEmployeeId() {
        return employeeId;
    }

    public String getEmployeeName() {
        return employeeName;
    }

    public String getPhotoUrl() {
        return photoUrl;
    }
}
