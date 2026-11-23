package com.example.nfcemployeewelcome.model;

import com.google.gson.annotations.SerializedName;

/** Mirrors backend schema IdentifyRequest: {"nfc_uid": "04A1B2C3D4"} */
public class IdentifyRequest {

    @SerializedName("nfc_uid")
    private final String nfcUid;

    public IdentifyRequest(String nfcUid) {
        this.nfcUid = nfcUid;
    }

    public String getNfcUid() {
        return nfcUid;
    }
}
