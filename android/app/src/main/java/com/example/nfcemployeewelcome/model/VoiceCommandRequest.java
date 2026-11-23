package com.example.nfcemployeewelcome.model;

public class VoiceCommandRequest {
    private final String text;

    public VoiceCommandRequest(String text) {
        this.text = text;
    }

    public String getText() {
        return text;
    }
}
