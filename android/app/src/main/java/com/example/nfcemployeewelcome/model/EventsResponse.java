package com.example.nfcemployeewelcome.model;

import com.google.gson.annotations.SerializedName;

import java.util.List;

/** Mirrors backend schema EventsResponse. */
public class EventsResponse {

    @SerializedName("server_id")
    private String serverId;

    @SerializedName("latest_id")
    private long latestId;

    @SerializedName("events")
    private List<ScanEvent> events;

    public String getServerId() {
        return serverId;
    }

    public long getLatestId() {
        return latestId;
    }

    public List<ScanEvent> getEvents() {
        return events;
    }
}
