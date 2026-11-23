package com.example.nfcemployeewelcome;

import android.Manifest;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.BitmapFactory;
import android.graphics.drawable.Drawable;
import android.graphics.drawable.GradientDrawable;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.speech.RecognizerIntent;
import android.util.Log;
import android.view.View;
import android.view.inputmethod.InputMethodManager;
import android.widget.ImageView;
import android.widget.TextView;
import android.widget.Toast;

import androidx.annotation.NonNull;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;

import com.example.nfcemployeewelcome.model.EventsResponse;
import com.example.nfcemployeewelcome.model.IdentifyRequest;
import com.example.nfcemployeewelcome.model.IdentifyResponse;
import com.example.nfcemployeewelcome.model.ScanEvent;
import com.example.nfcemployeewelcome.model.VoiceCommandRequest;
import com.example.nfcemployeewelcome.model.VoiceCommandResponse;
import com.example.nfcemployeewelcome.network.ApiClient;
import com.example.nfcemployeewelcome.network.ApiService;
import com.example.nfcemployeewelcome.nfc.NfcUtils;
import com.example.nfcemployeewelcome.tts.TtsManager;
import com.google.android.material.button.MaterialButton;
import com.google.android.material.materialswitch.MaterialSwitch;
import com.google.android.material.textfield.TextInputEditText;
import com.google.android.material.textfield.TextInputLayout;

import java.io.IOException;
import java.io.InputStream;
import java.io.InterruptedIOException;
import java.net.ConnectException;
import java.net.NoRouteToHostException;
import java.net.UnknownHostException;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Locale;

import okhttp3.ResponseBody;
import retrofit2.Call;
import retrofit2.Callback;
import retrofit2.Response;

/**
 * The phone does NOT read NFC. A USB reader on the laptop (usb_reader.py) reports cards to the
 * backend; this screen polls the backend for new scan events, shows them and speaks the welcome.
 */
public class MainActivity extends AppCompatActivity implements TtsManager.Listener {

    private static final String TAG = "NfcWelcome";

    private static final long POLL_INTERVAL_MS = 1000L;
    private static final long POLL_RETRY_INTERVAL_MS = 3000L;
    private static final long STATUS_RESET_MS = 6000L;
    private static final String EMPTY = "—";

    private static final int REQUEST_RECORD_AUDIO_PERMISSION = 1001;
    private static final int REQUEST_VOICE_COMMAND = 1002;

    private enum ScanState {
        WAITING(R.string.status_waiting, R.color.status_neutral),
        IDENTIFYING(R.string.status_identifying, R.color.primary),
        IDENTIFIED(R.string.status_identified, R.color.success),
        UNKNOWN(R.string.status_unknown, R.color.error),
        BACKEND_ERROR(R.string.status_backend_error, R.color.error);

        final int labelRes;
        final int colorRes;

        ScanState(int labelRes, int colorRes) {
            this.labelRes = labelRes;
            this.colorRes = colorRes;
        }
    }

    private ApiService apiService;
    private TtsManager ttsManager;

    // Polling state (main thread only)
    private final Handler uiHandler = new Handler(Looper.getMainLooper());
    private final Runnable pollRunnable = this::pollOnce;
    private final Runnable resetStatusRunnable = () -> setScanState(ScanState.WAITING, null);
    private boolean polling = false;
    private int pollGeneration = 0;
    private Call<EventsResponse> pollCall;
    private String serverId;
    private Long lastEventId; // null = not yet synchronised with the server

    // Test Mode state
    private Call<IdentifyResponse> testCall;
    private int testCounter = 0;

    // Voice recognition
    private Call<VoiceCommandResponse> voiceCall;

    private final SimpleDateFormat timeFormat =
            new SimpleDateFormat("dd MMM yyyy, hh:mm:ss a", Locale.getDefault());

    // Views
    private TextView tvConnection, tvReadyTitle, tvInstruction, tvScanStatus, tvScanDetail, tvTtsWarning;
    private TextView tvEmployeeName, tvEmployeeId, tvCardUid;
    private ImageView ivEmployeePhoto;
    private TextView tvLastName, tvLastId, tvLastTime;
    private MaterialButton btnTestUid;
    private MaterialSwitch switchTestMode;
    private View layoutTestBody;
    private TextInputLayout tilTestUid;
    private TextInputEditText etTestUid;
    private TextView tvVoiceStatus;
    private MaterialButton btnVoiceCommand;

    // ------------------------------------------------------------------ lifecycle

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        bindViews();
        setupListeners();

        try {
            apiService = ApiClient.getService();
        } catch (Exception e) { // e.g. invalid BASE_URL
            Log.e(TAG, "Could not create API client", e);
            apiService = null;
        }

        ttsManager = new TtsManager(this, this);
        setConnection(false, apiService == null ? getString(R.string.err_config) : null);
        tvReadyTitle.setText(R.string.ready_title);
        setScanState(ScanState.WAITING, null);
    }

    @Override
    protected void onResume() {
        super.onResume();
        startPolling();
    }

    @Override
    protected void onPause() {
        super.onPause();
        stopPolling();
        if (ttsManager != null) {
            ttsManager.stop();
        }
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        stopPolling();
        uiHandler.removeCallbacksAndMessages(null);
        testCounter++;
        if (testCall != null) {
            testCall.cancel();
            testCall = null;
        }
        if (ttsManager != null) {
            ttsManager.shutdown();
            ttsManager = null;
        }
        if (voiceCall != null) {
            voiceCall.cancel();
            voiceCall = null;
        }
    }

    private void bindViews() {
        tvConnection = findViewById(R.id.tvNfcStatus);
        tvReadyTitle = findViewById(R.id.tvReadyTitle);
        tvInstruction = findViewById(R.id.tvInstruction);
        tvScanStatus = findViewById(R.id.tvScanStatus);
        tvScanDetail = findViewById(R.id.tvScanDetail);
        tvTtsWarning = findViewById(R.id.tvTtsWarning);
        tvEmployeeName = findViewById(R.id.tvEmployeeName);
        tvEmployeeId = findViewById(R.id.tvEmployeeId);
        tvCardUid = findViewById(R.id.tvNfcUid);
        ivEmployeePhoto = findViewById(R.id.ivEmployeePhoto);
        tvLastName = findViewById(R.id.tvLastName);
        tvLastId = findViewById(R.id.tvLastId);
        tvLastTime = findViewById(R.id.tvLastTime);
        btnTestUid = findViewById(R.id.btnTestUid);
        switchTestMode = findViewById(R.id.switchTestMode);
        layoutTestBody = findViewById(R.id.layoutTestBody);
        tilTestUid = findViewById(R.id.tilTestUid);
        etTestUid = findViewById(R.id.etTestUid);
        tvVoiceStatus = findViewById(R.id.tvVoiceStatus);
        btnVoiceCommand = findViewById(R.id.btnVoiceCommand);
    }

    private void setupListeners() {
        switchTestMode.setOnCheckedChangeListener((button, checked) ->
                layoutTestBody.setVisibility(checked ? View.VISIBLE : View.GONE));

        btnTestUid.setOnClickListener(v -> {
            String raw = etTestUid.getText() == null ? "" : etTestUid.getText().toString();
            String uid = NfcUtils.normalizeUid(raw);
            if (uid.isEmpty()) {
                tilTestUid.setError(getString(R.string.test_uid_required));
                return;
            }
            tilTestUid.setError(null);
            hideKeyboard(v);
            runManualTest(uid);
        });

        btnVoiceCommand.setOnClickListener(v -> startVoiceCommand());
    }

    // ------------------------------------------------------------------ polling the server

    private void startPolling() {
        if (apiService == null) {
            return;
        }
        polling = true;
        pollGeneration++;
        // Re-sync on every resume so scans that happened while the app was away are not announced late.
        serverId = null;
        lastEventId = null;
        uiHandler.removeCallbacks(pollRunnable);
        uiHandler.post(pollRunnable);
    }

    private void stopPolling() {
        polling = false;
        pollGeneration++;
        uiHandler.removeCallbacks(pollRunnable);
        if (pollCall != null) {
            pollCall.cancel();
            pollCall = null;
        }
    }

    private void scheduleNextPoll(long delayMs) {
        if (polling) {
            uiHandler.removeCallbacks(pollRunnable);
            uiHandler.postDelayed(pollRunnable, delayMs);
        }
    }

    private void pollOnce() {
        if (!polling || apiService == null) {
            return;
        }
        final int generation = pollGeneration;
        final Call<EventsResponse> call = apiService.getEvents(lastEventId);
        pollCall = call;

        call.enqueue(new Callback<EventsResponse>() {
            @Override
            public void onResponse(@NonNull Call<EventsResponse> c, @NonNull Response<EventsResponse> response) {
                if (generation != pollGeneration || isFinishing() || isDestroyed()) {
                    return;
                }
                pollCall = null;
                EventsResponse body = response.body();
                if (response.isSuccessful() && body != null) {
                    setConnection(true, null);
                    handleEvents(body);
                    scheduleNextPoll(POLL_INTERVAL_MS);
                } else {
                    setConnection(false, httpDetail(response.code()));
                    scheduleNextPoll(POLL_RETRY_INTERVAL_MS);
                }
            }

            @Override
            public void onFailure(@NonNull Call<EventsResponse> c, @NonNull Throwable t) {
                if (c.isCanceled() || generation != pollGeneration || isFinishing() || isDestroyed()) {
                    return;
                }
                pollCall = null;
                Log.w(TAG, "Poll failed", t);
                setConnection(false, throwableDetail(t));
                scheduleNextPoll(POLL_RETRY_INTERVAL_MS);
            }
        });
    }

    private void handleEvents(EventsResponse body) {
        // First successful poll (or backend restarted): just remember where we are, replay nothing.
        if (lastEventId == null || serverId == null || !serverId.equals(body.getServerId())) {
            serverId = body.getServerId();
            lastEventId = body.getLatestId();
            return;
        }

        List<ScanEvent> events = body.getEvents();
        if (events == null || events.isEmpty()) {
            return;
        }

        ScanEvent lastSuccess = null;
        for (ScanEvent event : events) {
            if (event.getId() > lastEventId) {
                lastEventId = event.getId();
            }
            showScan(event.getNfcUid(), event.isSuccess(), event.getEmployeeName(),
                    event.getEmployeeId(), event.getMessage(), event.getPhotoUrl(), false);
            if (isIdentified(event.isSuccess(), event.getEmployeeName())) {
                lastSuccess = event;
            }
        }

        // If several cards arrived within one poll, announce only the most recent identified one.
        if (lastSuccess != null && ttsManager != null) {
            ttsManager.speak("Welcome, " + lastSuccess.getEmployeeName().trim());
        }
    }

    // ------------------------------------------------------------------ Test Mode (no reader involved)

    private void runManualTest(final String uid) {
        if (apiService == null) {
            setScanState(ScanState.BACKEND_ERROR, getString(R.string.err_config));
            return;
        }
        if (testCall != null) {
            testCall.cancel();
        }
        final int requestId = ++testCounter;
        tvCardUid.setText(getString(R.string.manual_suffix, uid));
        tvEmployeeName.setText(EMPTY);
        tvEmployeeId.setText(EMPTY);
        setScanState(ScanState.IDENTIFYING, null);

        final Call<IdentifyResponse> call = apiService.identifyEmployee(new IdentifyRequest(uid));
        testCall = call;
        call.enqueue(new Callback<IdentifyResponse>() {
            @Override
            public void onResponse(@NonNull Call<IdentifyResponse> c, @NonNull Response<IdentifyResponse> response) {
                if (requestId != testCounter || isFinishing() || isDestroyed()) {
                    return;
                }
                testCall = null;
                IdentifyResponse body = response.body();
                if (response.isSuccessful() && body != null) {
                    showScan(getString(R.string.manual_suffix, uid), body.isSuccess(), body.getEmployeeName(),
                            body.getEmployeeId(), body.getMessage(), body.getPhotoUrl(), true);
                } else {
                    setScanState(ScanState.BACKEND_ERROR, httpDetail(response.code()));
                }
            }

            @Override
            public void onFailure(@NonNull Call<IdentifyResponse> c, @NonNull Throwable t) {
                if (c.isCanceled() || requestId != testCounter || isFinishing() || isDestroyed()) {
                    return;
                }
                testCall = null;
                setScanState(ScanState.BACKEND_ERROR, throwableDetail(t));
            }
        });
    }

    // ------------------------------------------------------------------ voice recognition

    private void startVoiceCommand() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
                != PackageManager.PERMISSION_GRANTED) {
            ActivityCompat.requestPermissions(this,
                    new String[]{Manifest.permission.RECORD_AUDIO}, REQUEST_RECORD_AUDIO_PERMISSION);
            return;
        }

        Intent intent = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
        intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);
        intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE, Locale.ENGLISH);
        intent.putExtra(RecognizerIntent.EXTRA_PROMPT, "Say turn on the light or turn off the light");
        intent.putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1);
        try {
            startActivityForResult(intent, REQUEST_VOICE_COMMAND);
        } catch (Exception e) {
            tvVoiceStatus.setText("Could not start voice recognition");
        }
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, @NonNull String[] permissions,
                                           @NonNull int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == REQUEST_RECORD_AUDIO_PERMISSION) {
            if (grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
                startVoiceCommand();
            } else {
                tvVoiceStatus.setText("Microphone permission is required");
            }
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode != REQUEST_VOICE_COMMAND || resultCode != RESULT_OK || data == null) {
            if (requestCode == REQUEST_VOICE_COMMAND) {
                tvVoiceStatus.setText("Voice command was cancelled");
            }
            return;
        }

        ArrayList<String> results = data.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS);
        if (results == null || results.isEmpty()) {
            tvVoiceStatus.setText("Could not understand the voice command");
            return;
        }

        String spokenText = results.get(0);
        tvVoiceStatus.setText("Heard: " + spokenText);
        sendVoiceCommand(spokenText);
    }

    private void sendVoiceCommand(String spokenText) {
        if (apiService == null) {
            tvVoiceStatus.setText(getString(R.string.err_config));
            return;
        }
        if (voiceCall != null) {
            voiceCall.cancel();
        }

        voiceCall = apiService.processVoiceCommand(new VoiceCommandRequest(spokenText));
        voiceCall.enqueue(new Callback<VoiceCommandResponse>() {
            @Override
            public void onResponse(@NonNull Call<VoiceCommandResponse> call,
                                   @NonNull Response<VoiceCommandResponse> response) {
                voiceCall = null;
                VoiceCommandResponse body = response.body();
                if (response.isSuccessful() && body != null) {
                    tvVoiceStatus.setText(body.getMessage());
                    if (ttsManager != null) {
                        ttsManager.speak(body.getMessage());
                    }
                } else {
                    tvVoiceStatus.setText(httpDetail(response.code()));
                }
            }

            @Override
            public void onFailure(@NonNull Call<VoiceCommandResponse> call,
                                  @NonNull Throwable throwable) {
                if (!call.isCanceled()) {
                    voiceCall = null;
                    tvVoiceStatus.setText(throwableDetail(throwable));
                }
            }
        });
    }

    // ------------------------------------------------------------------ showing results

    private boolean isIdentified(boolean success, String name) {
        return success && name != null && !name.trim().isEmpty();
    }

    private void showScan(String uidText, boolean success, String name, String employeeId,
                          String message, String photoUrl, boolean speak) {
        tvCardUid.setText(uidText == null ? EMPTY : uidText);

        if (isIdentified(success, name)) {
            String cleanName = name.trim();
            String id = employeeId == null ? EMPTY : employeeId;

            tvEmployeeName.setText(cleanName);
            tvEmployeeId.setText(id);
            loadEmployeePhoto(photoUrl);

            tvLastName.setText(cleanName);
            tvLastId.setText(getString(R.string.last_id_format, id));
            tvLastTime.setText(getString(R.string.last_time_format, timeFormat.format(new Date())));
            tvLastId.setVisibility(View.VISIBLE);
            tvLastTime.setVisibility(View.VISIBLE);

            setScanState(ScanState.IDENTIFIED, "Welcome, " + cleanName);
            if (speak && ttsManager != null) {
                ttsManager.speak("Welcome, " + cleanName);
            }
        } else {
            // Unknown card: show it, but never announce a welcome.
            tvEmployeeName.setText(R.string.unregistered_card);
            tvEmployeeId.setText(EMPTY);
            ivEmployeePhoto.setImageDrawable(null);
            ivEmployeePhoto.setVisibility(View.GONE);
            setScanState(ScanState.UNKNOWN, message);
        }
    }

    private void loadEmployeePhoto(String photoUrl) {
        if (photoUrl == null || photoUrl.trim().isEmpty() || apiService == null) {
            ivEmployeePhoto.setImageDrawable(null);
            ivEmployeePhoto.setVisibility(View.GONE);
            return;
        }

        apiService.getPhoto(photoUrl).enqueue(new Callback<ResponseBody>() {
            @Override
            public void onResponse(@NonNull Call<ResponseBody> call, @NonNull Response<ResponseBody> response) {
                if (isFinishing() || isDestroyed()) {
                    return;
                }
                ResponseBody body = response.body();
                if (!response.isSuccessful() || body == null) {
                    ivEmployeePhoto.setImageDrawable(null);
                    ivEmployeePhoto.setVisibility(View.GONE);
                    return;
                }
                try (InputStream input = body.byteStream()) {
                    ivEmployeePhoto.setImageBitmap(BitmapFactory.decodeStream(input));
                    ivEmployeePhoto.setVisibility(View.VISIBLE);
                } catch (IOException e) {
                    Log.w(TAG, "Could not decode employee photo", e);
                    ivEmployeePhoto.setImageDrawable(null);
                    ivEmployeePhoto.setVisibility(View.GONE);
                }
            }

            @Override
            public void onFailure(@NonNull Call<ResponseBody> call, @NonNull Throwable t) {
                if (!call.isCanceled() && !isFinishing() && !isDestroyed()) {
                    Log.w(TAG, "Could not load employee photo", t);
                    ivEmployeePhoto.setImageDrawable(null);
                    ivEmployeePhoto.setVisibility(View.GONE);
                }
            }
        });
    }

    private void setConnection(boolean connected, String detail) {
        if (connected) {
            setPill(tvConnection, R.string.conn_connected, R.color.success);
            tvReadyTitle.setText(R.string.ready_title);
            tvInstruction.setText(R.string.instruction_tap);
        } else {
            setPill(tvConnection, R.string.conn_disconnected, R.color.error);
            tvReadyTitle.setText(R.string.unavailable_title);
            tvInstruction.setText(detail == null ? getString(R.string.err_unreachable) : detail);
        }
    }

    private void setScanState(ScanState state, String detail) {
        uiHandler.removeCallbacks(resetStatusRunnable);
        setPill(tvScanStatus, state.labelRes, state.colorRes);

        if (detail == null || detail.isEmpty()) {
            tvScanDetail.setVisibility(View.GONE);
        } else {
            tvScanDetail.setText(detail);
            tvScanDetail.setVisibility(View.VISIBLE);
        }

        boolean terminal = state == ScanState.IDENTIFIED
                || state == ScanState.UNKNOWN
                || state == ScanState.BACKEND_ERROR;
        if (terminal) {
            uiHandler.postDelayed(resetStatusRunnable, STATUS_RESET_MS);
        }
    }

    private void setPill(TextView pill, int textRes, int colorRes) {
        pill.setText(textRes);
        Drawable background = pill.getBackground().mutate();
        if (background instanceof GradientDrawable) {
            ((GradientDrawable) background).setColor(ContextCompat.getColor(this, colorRes));
        }
    }

    private String httpDetail(int code) {
        if (code == 422) {
            return getString(R.string.err_invalid_request);
        }
        if (code >= 500) {
            return getString(R.string.err_server, code);
        }
        return getString(R.string.err_http, code);
    }

    private String throwableDetail(Throwable t) {
        if (t instanceof InterruptedIOException) { // includes SocketTimeoutException / call timeout
            return getString(R.string.err_timeout);
        }
        if (t instanceof UnknownHostException
                || t instanceof ConnectException
                || t instanceof NoRouteToHostException) {
            return getString(R.string.err_unreachable);
        }
        if (t instanceof IOException) {
            return getString(R.string.err_network, String.valueOf(t.getMessage()));
        }
        return getString(R.string.err_unexpected, String.valueOf(t.getMessage()));
    }

    private void hideKeyboard(View view) {
        InputMethodManager imm = (InputMethodManager) getSystemService(Context.INPUT_METHOD_SERVICE);
        if (imm != null) {
            imm.hideSoftInputFromWindow(view.getWindowToken(), 0);
        }
    }

    // ------------------------------------------------------------------ TtsManager.Listener

    @Override
    public void onTtsInitFailed(String reason) {
        if (isFinishing() || isDestroyed()) {
            return;
        }
        tvTtsWarning.setText(getString(R.string.tts_warning, reason));
        tvTtsWarning.setVisibility(View.VISIBLE);
        Toast.makeText(this, getString(R.string.tts_warning, reason), Toast.LENGTH_LONG).show();
    }

    @Override
    public void onTtsError(String reason) {
        if (isFinishing() || isDestroyed()) {
            return;
        }
        Toast.makeText(this, reason, Toast.LENGTH_SHORT).show();
    }
}
