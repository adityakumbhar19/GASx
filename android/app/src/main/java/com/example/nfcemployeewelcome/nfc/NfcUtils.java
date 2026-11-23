package com.example.nfcemployeewelcome.nfc;

import java.util.Locale;

public final class NfcUtils {

    private static final char[] HEX = "0123456789ABCDEF".toCharArray();

    private NfcUtils() {
    }

    /** Converts Tag.getId() bytes to an uppercase hex string, e.g. {0x04,0xA1} -> "04A1". */
    public static String bytesToHex(byte[] bytes) {
        if (bytes == null) {
            return "";
        }
        char[] out = new char[bytes.length * 2];
        for (int i = 0; i < bytes.length; i++) {
            int v = bytes[i] & 0xFF;
            out[i * 2] = HEX[v >>> 4];
            out[i * 2 + 1] = HEX[v & 0x0F];
        }
        return new String(out);
    }

    /** Removes spaces, ':' and '-' and uppercases user-typed UIDs. */
    public static String normalizeUid(String raw) {
        if (raw == null) {
            return "";
        }
        return raw.replaceAll("[\\s:\\-]", "").toUpperCase(Locale.ROOT);
    }
}
