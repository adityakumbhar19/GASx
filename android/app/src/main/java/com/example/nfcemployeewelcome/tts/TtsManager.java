package com.example.nfcemployeewelcome.tts;

import android.content.Context;
import android.os.Handler;
import android.os.Looper;
import android.speech.tts.TextToSpeech;
import android.speech.tts.UtteranceProgressListener;
import android.util.Log;

import com.example.nfcemployeewelcome.R;

import java.util.Locale;

/**
 * Wraps Android TextToSpeech. Speech requested before initialization completes is held and
 * spoken as soon as the engine is ready; if initialization fails, the listener is told and the
 * app keeps working without voice. All Listener callbacks arrive on the main thread.
 */
public class TtsManager {

    private static final String TAG = "TtsManager";

    public interface Listener {
        void onTtsInitFailed(String reason);

        void onTtsError(String reason);
    }

    private enum State { INITIALIZING, READY, FAILED }

    private final Context appContext;
    private final Listener listener;
    private final Handler mainHandler = new Handler(Looper.getMainLooper());

    private TextToSpeech tts;
    private volatile State state = State.INITIALIZING;
    private String pendingText;
    private int utteranceCounter = 0;

    public TtsManager(Context context, Listener listener) {
        this.appContext = context.getApplicationContext();
        this.listener = listener;
        try {
            tts = new TextToSpeech(appContext, this::onInit);
        } catch (Exception e) {
            Log.e(TAG, "TextToSpeech construction failed", e);
            failInit(appContext.getString(R.string.tts_init_failed));
        }
    }

    private void onInit(int status) {
        if (tts == null) {
            return; // already shut down
        }
        if (status != TextToSpeech.SUCCESS) {
            failInit(appContext.getString(R.string.tts_init_failed));
            return;
        }
        int langResult = tts.setLanguage(Locale.ENGLISH);
        if (langResult == TextToSpeech.LANG_MISSING_DATA
                || langResult == TextToSpeech.LANG_NOT_SUPPORTED) {
            failInit(appContext.getString(R.string.tts_no_english));
            return;
        }

        tts.setOnUtteranceProgressListener(new UtteranceProgressListener() {
            @Override
            public void onStart(String utteranceId) {
            }

            @Override
            public void onDone(String utteranceId) {
            }

            @Override
            @SuppressWarnings("deprecation")
            public void onError(String utteranceId) {
                postError(appContext.getString(R.string.tts_speak_failed));
            }

            @Override
            public void onError(String utteranceId, int errorCode) {
                postError(appContext.getString(R.string.tts_speak_failed) + " (" + errorCode + ")");
            }
        });

        state = State.READY;
        Log.d(TAG, "TextToSpeech ready");

        if (pendingText != null) {
            String text = pendingText;
            pendingText = null;
            speakNow(text);
        }
    }

    /** Speaks the text (interrupting anything currently being spoken). Safe to call at any time. */
    public void speak(String text) {
        if (text == null || text.isEmpty()) {
            return;
        }
        switch (state) {
            case READY:
                speakNow(text);
                break;
            case INITIALIZING:
                pendingText = text; // spoken once init succeeds
                break;
            case FAILED:
            default:
                postError(appContext.getString(R.string.tts_unavailable));
                break;
        }
    }

    private void speakNow(String text) {
        try {
            utteranceCounter++;
            int result = tts.speak(text, TextToSpeech.QUEUE_FLUSH, null, "welcome-" + utteranceCounter);
            if (result == TextToSpeech.ERROR) {
                postError(appContext.getString(R.string.tts_speak_failed));
            }
        } catch (Exception e) {
            Log.e(TAG, "speak failed", e);
            postError(appContext.getString(R.string.tts_speak_failed));
        }
    }

    /** Stops current speech (call from onPause). */
    public void stop() {
        pendingText = null;
        if (tts != null && state == State.READY) {
            try {
                tts.stop();
            } catch (Exception e) {
                Log.w(TAG, "stop failed", e);
            }
        }
    }

    /** Releases the engine (call from onDestroy). */
    public void shutdown() {
        pendingText = null;
        if (tts != null) {
            try {
                tts.stop();
                tts.shutdown();
            } catch (Exception e) {
                Log.w(TAG, "shutdown failed", e);
            }
            tts = null;
        }
        state = State.FAILED;
    }

    private void failInit(String reason) {
        state = State.FAILED;
        pendingText = null;
        mainHandler.post(() -> listener.onTtsInitFailed(reason));
    }

    private void postError(String reason) {
        mainHandler.post(() -> listener.onTtsError(reason));
    }
}
