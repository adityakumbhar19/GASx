package com.example.nfcemployeewelcome.model;

import com.google.gson.annotations.SerializedName;

/** Mirrors backend schema ScanEvent. */
public class ScanEvent {

    @SerializedName("id")
    private long id;

    @SerializedName("timestamp")
    private String timestamp;

    @SerializedName("nfc_uid")
    private String nfcUid;

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

    public long getId() {
        return id;
    }

    public String getTimestamp() {
        return timestamp;
    }

    public String getNfcUid() {
        return nfcUid;
    }

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
