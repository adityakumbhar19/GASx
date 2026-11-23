package com.example.nfcemployeewelcome.network;

import com.example.nfcemployeewelcome.BuildConfig;

import java.util.concurrent.TimeUnit;

import okhttp3.OkHttpClient;
import okhttp3.logging.HttpLoggingInterceptor;
import retrofit2.Retrofit;
import retrofit2.converter.gson.GsonConverterFactory;

/** Builds the Retrofit client. The base URL comes from BuildConfig.BASE_URL (see app/build.gradle). */
public final class ApiClient {

    private static ApiService service;

    private ApiClient() {
    }

    /**
     * @throws IllegalArgumentException if BuildConfig.BASE_URL is not a valid URL
     *                                  (e.g. you forgot to replace YOUR_LAPTOP_IP).
     */
    public static synchronized ApiService getService() {
        if (service == null) {
            String baseUrl = BuildConfig.BASE_URL;
            if (!baseUrl.endsWith("/")) {
                baseUrl = baseUrl + "/";
            }

            HttpLoggingInterceptor logging = new HttpLoggingInterceptor();
            logging.setLevel(BuildConfig.DEBUG
                    ? HttpLoggingInterceptor.Level.BODY
                    : HttpLoggingInterceptor.Level.NONE);

            OkHttpClient client = new OkHttpClient.Builder()
                    .connectTimeout(8, TimeUnit.SECONDS)
                    .readTimeout(10, TimeUnit.SECONDS)
                    .writeTimeout(10, TimeUnit.SECONDS)
                    .callTimeout(15, TimeUnit.SECONDS)
                    .addInterceptor(logging)
                    .build();

            Retrofit retrofit = new Retrofit.Builder()
                    .baseUrl(baseUrl)
                    .client(client)
                    .addConverterFactory(GsonConverterFactory.create())
                    .build();

            service = retrofit.create(ApiService.class);
        }
        return service;
    }
}
