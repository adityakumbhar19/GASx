package com.example.nfcemployeewelcome.network;

import com.example.nfcemployeewelcome.model.EventsResponse;
import com.example.nfcemployeewelcome.model.IdentifyRequest;
import com.example.nfcemployeewelcome.model.IdentifyResponse;
import com.example.nfcemployeewelcome.model.VoiceCommandRequest;
import com.example.nfcemployeewelcome.model.VoiceCommandResponse;

import retrofit2.Call;
import retrofit2.http.Body;
import retrofit2.http.GET;
import retrofit2.http.POST;
import retrofit2.http.Query;
import retrofit2.http.Url;
import okhttp3.ResponseBody;

public interface ApiService {

    /** Used by Test Mode only (does not create a scan event). */
    @POST("api/v1/employee/identify")
    Call<IdentifyResponse> identifyEmployee(@Body IdentifyRequest request);

    /**
     * Polls for scans reported by the USB reader.
     * afterId == null -> the server only returns latest_id (no history is replayed).
     */
    @GET("api/v1/events")
    Call<EventsResponse> getEvents(@Query("after_id") Long afterId);

    /** Loads the JPEG stored by the backend in PostgreSQL. */
    @GET
    Call<ResponseBody> getPhoto(@Url String photoUrl);

    /** 
     * Sends a voice command to the FastAPI backend.
     */
    @POST("api/v1/employee/voice-command")
    Call<VoiceCommandResponse> sendVoiceCommand(@Body VoiceCommandRequest request);

    @POST("api/v1/voice-command")
    Call<VoiceCommandResponse> processVoiceCommand(@Body VoiceCommandRequest request);
}
