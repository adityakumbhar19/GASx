package com.example.nfcemployeewelcome.model;

public class VoiceCommandResponse {
    private boolean success;
    private String action;
    private String spoken_text;
    private String message;

    public boolean isSuccess() {
        return success;
    }

    public String getAction() {
        return action;
    }

    public String getSpokenText() {
        return spoken_text;
    }

    public String getMessage() {
        return message;
    }
}
