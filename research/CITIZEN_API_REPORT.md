# Citizen Android App — Private API Reverse-Engineering Report

**Target:** Citizen (`sp0n.citizen`), version `0.1308.0` (versionCode `1140`), built 2026 — downloaded from APKPure as `sp0n.citizen@0.1308.0.xapk`, minSdk 29 / targetSdk 36.
**Method:** static analysis of the decompiled APK (jadx 1.x deobfuscation, apktool resources) plus limited **read-only** live probing of `data.sp0n.io` GET endpoints and the WebSocket handshake. No accounts were created or modified, no authenticated endpoints were exercised, no incidents were submitted.
**Status tags:** `[VERIFIED]` = confirmed by live observation or explicit code; `[CODE]` = read from decompiled source; `[INFERRED]` = hypothesis not yet confirmed.

---

## 1. Executive summary

* Citizen's backend is a single API host, **`https://data.sp0n.io`**, fronted by Google infrastructure (responses carry `Via: 1.1 google`). A staging twin exists at `https://staging.sp0n.io`.
* The app talks to it three ways:
  1. **REST/Retrofit** over HTTPS for essentially everything (incident details, feeds, auth, social, chat history, premium "Protect" features).
  2. **A WebSocket** at `wss://data.sp0n.io/websocket` — used **only for chat and Protect (premium agent) sessions**, *not* for the incident feed.
  3. **FCM push notifications** (`sp0n.citizen.services.CitizenFirebaseMessagingService`) — the real-time alerting channel for new incidents.
* The live incident map is rendered from **Mapbox vector tiles** (Mapbox Maps SDK v10, `com.mapbox.maps.MapView`) served unauthenticated at `GET /v1/tile/incidents/{x}/{y}/{z}.pbf` (MVT/protobuf, layer name `incidents`). `[VERIFIED]`
* **Large parts of the read API require no credentials at all** — verified by direct requests: incident details (`v1/v2/v3 incident`), batch fetch, related incidents, map sources, service-area discovery, homescreen status v1, safety geocoding, the `v2/news/feed`, the variable-settings bootstrap, and the incident vector tiles. `[VERIFIED]`
* Endpoints that drive personalized state (`v3/homescreen/mapIncidents`, `v2/homescreen/status`, `v1/homescreen/feed`, `v1/search`, `v1/variable_settings`, `v1/users/nearby`, `v1/friends/*`, notifications, chat, reporting) return `401 {"error":"invalid token supplied"}` or `{"error":"access token missing"}` without an `x-access-token`. `[VERIFIED]`
* Auth is phone-number OTP (or Google sign-in) exchanging a code for a long-lived `userToken` sent as the `x-access-token` header on every request. `[CODE + VERIFIED shape]`
* No certificate pinning is configured (`res/xml/network_security_config.xml` is empty; no `CertificatePinner` in the OkHttp builders), so app traffic can be observed with a standard MITM proxy on a device you control. `[VERIFIED by code]`

**Bottom line for a third-party incident feed:** an unauthenticated consumer can reconstruct the live incident feed by polling the vector-tile endpoint over a bounding box (map tiles contain `incident_id`, position, title, category, severity, lifecycle state, timestamps) and hydrating details via `GET /v3/incident/{id}` — all without credentials. Server-push via WebSocket or FCM is *not* available to third parties (WS requires a real user token; FCM is tied to a registered device), so polling is the only viable mechanism.

---

## 2. App architecture (network-relevant)

| Component | Where | Notes |
|---|---|---|
| Application | `sp0n.citizen.CitizenApplication` | AppInitializers via androidx.startup: `LoggingInitializer`, `VariableSettingsInitializer`, `IterableInitializer`, `DependencyGraphInitializer` |
| DI | Dagger/Hilt modules: `sp0n.citizen.api.ApiModule`, `sp0n.citizen.data.di.ApiModule2`, `sp0n.citizen.core.api.retrofit.NetworkingModule`, `DeviceModule` | |
| HTTP client | OkHttp (`p000.dib`), 10 s connect/read/write timeouts; upload client 10 min | |
| REST | Retrofit (`p000.kdd`), Gson converter (`f57`) for most APIs; kotlinx-serialization (`ay5`/`fce`) for the "coroutine" Retrofit | Return type is a custom `NetworkResult` (`p000.oya`) |
| WebSocket | `org.java_websocket` client (`p000.u9h` = WebSocketClient, `p000.h75` = Draft) | `SocketConnection` → `SocketConnection2` (Rx) and `SocketConnectionFlow` (coroutines) |
| Push | FCM → `CitizenFirebaseMessagingService` → `MessageReceivedUseCase` (`p000.paa`) → `ShowNotificationUseCase` (`p000.soe`); Iterable SDK handled first | |
| Maps | Mapbox Maps SDK v10 (`com.mapbox.maps.MapView`); incident layer = vector source `all_incidents` with `tiles: [incidentTileURL]` | `sp0n.citizen.safetyhome.C6649s` |
| Analytics | Segment (`writeKey uPST0q1x…<redacted>`) proxied to `https://metrics.sp0n.io`; AppsFlyer; Iterable (`api.iterable.com`); Branch (`api2.branch.io`, key `key_live_iifH…<redacted>`) | `DeviceModule.Companion.provideSegment` |
| Streaming media | Twilio (Protect agent video), Agora/IMS libs present for broadcast video | out of scope |
| Debug surface | `sp0n.citizen.debug.*` activities incl. `DebugNetworkRequestsActivity` (Flipper-style network log), `DebugNotificationsCreatorActivity` — present but non-exported | |

Obfuscated-name → real-name mapping used throughout (from `compiled from` comments):
`kdd`=Retrofit, `ww6`=@GET, `qrb`=@POST, `q64`=@DELETE, `xwb`=@Path, `qvc`=@Query, `u91`=@Body, `oya`=NetworkResult, `xn3`=Continuation, `dib`=OkHttpClient, `u9h`=WebSocketClient, `h9b`=Observable/BehaviorSubject-ish, `ema`/`i6f`/`j6f`=MutableStateFlow/StateFlow.

---

## 3. Hosts and build configuration

`sp0n.citizen.api.BuildConfigModule.provideBuildConfigInfo` (literal):

```java
return new BuildConfigInfo("0.1308.0", 1140,
    "https://assets.citizen.com",          // assetsUrl
    "https://data.sp0n.io",                // dataUrl  (REST + tiles)
    "wss://data.sp0n.io/websocket",        // socket2Url
    !StringsKt.m12974z("https://data.sp0n.io", "staging", false), // isProduction
    "b384d0cf…<redacted>",                 // clientKey (embedded JWT-signing key)
    "fcmProdAll",                          // notifTopic (FCM topic)
    "citizenProd",                         // flavor
    false);                                // isInstrumentedTest
```

| Host | Purpose | Verified response |
|---|---|---|
| `data.sp0n.io` | Main REST API, incident tiles, WebSocket | `GET /healthz` → `200 OK` |
| `staging.sp0n.io` | Staging backend | `GET /healthz` → `200 OK` |
| `assets.citizen.com` | Static assets / file downloads (Retrofit: `provideAssetsDownloadRetrofit`) | — |
| `metrics.sp0n.io` | Segment analytics proxy | — |
| `go.citizen.com`, `i.citizen.com`, `citizen.com` | App-links / deep links | manifest `app_links_host*` strings |
| `api.iterable.com`, `api2.branch.io`, `*.googleapis.com`, `api.mapbox.com`, `*.tilestream.net` | Third-party SDKs | — |

Deep-link schemes (manifest): `https?://go.citizen.com/`, `https?://citizen.com/world-cup-hub`, `https?://i.citizen.com/`, iterable link hosts, and `citizen://open`.

---

## 4. HTTP layer — headers, client config, errors

`NetworkingModule.provideOkHttpClient` builds the shared client: 10 s timeouts, one interceptor that adds client + auth headers, plus a `CustomLoggingInterceptor` and an OkReplay interceptor.

```java
// NetworkingModule.addClientHeaders / addAuthHeaders
c3835a.m14115a("User-Agent", str + "-Android/0.1308.0-" + 1140);   // str = "Vigilante"
c3835a.m14115a("build-number", "1140");
c3835a.m14115a("androidAPI", String.valueOf(Build.VERSION.SDK_INT));
c3835a.m14115a("Accept-Language", locale.toLanguageTag());        // if non-empty
// ...
if (userToken != null) c3835a.m14115a("x-access-token", userToken);
```

Effective request headers:

```
User-Agent: Vigilante-Android/0.1308.0-1140
build-number: 1140
androidAPI: <sdk int, e.g. 34>
Accept-Language: en-US
x-access-token: <userToken>          # only when logged in
```

Notes:
* `userAgentPrefix` string resource = **`Vigilante`** (the app's original name).
* The upload client (`provideUploadOkHttpClient`) uses the same headers, 10-min write timeout and a `ProgressFriendlySocketFactory`.
* A separate `provideFileDownloadOkHttpClient` (assets, `assets.citizen.com`) sends client headers only — no token.
* Error envelope observed: `{"error":"<message>"}` with HTTP 4xx (`401 invalid token supplied`, `401 access token missing`, `400 invalid request: too short`). `[VERIFIED]`
* `RxJava2ErrorHandlingCallAdapterFactory` wraps RxJava calls into `NetworkResult` (`p000.oya`, compiled from `NetworkResult.kt`).
* There is **no request signing / attestation** visible in the interceptor chain — requests carry only the headers above. Play Integrity/SafetyNet was not observed in the networking path (though the app does contain Play-services code for other purposes). `[CODE]`

---

## 5. Authentication

### 5.1 Token model

`SessionManager` (`sp0n.citizen.data.common.SessionManager`):

* `userToken` + `userId` persisted in SharedPreferences under keys `"userToken"`/user-id; `isAuthenticated()` requires both non-null.
* `setUserTokenAndId(token, uid)` is called after successful code validation; `observeAuthenticatedState()` (BehaviorSubject<Boolean>) drives socket bootstrap.
* There is **no token refresh flow in the app** — the `userToken` obtained at login is used until logout (`/v1/auth/reset_user` exists to wipe). `[CODE]`

### 5.2 Login endpoints — `sp0n.citizen.api.onboarding.OnBoardingApiRetrofit`

| Method | Path | Request DTO | Response |
|---|---|---|---|
| POST | `v1/auth/request_code` | `PhoneCodeRequestDTO{phoneNumber, existingUser, androidAutocomplete}` | Unit |
| POST | `v1.2/auth/validate_code` | `ValidatePhoneCodeRequestDTO{code, deviceId, latitude, longitude, phoneNumber}` | `CodeVerificationResponseDTO` |
| POST | `v1/auth/google` | `GoogleAuthRequestDTO` | `CodeVerificationResponseDTO` |
| POST | `v1/auth/request_email_code` | `VerificationEmailRequestDTO` | Unit |
| POST | `v1/auth/validate_email_code` | `VerificationEmailCodeRequestDTO` | `CodeVerificationResponseDTO` |
| POST | `v1/auth/reset_user` | — (`UserRetrofitApi`) | — |

`CodeVerificationResponseDTO` fields: `{ "userToken": String, "uid": String, "registered": Boolean }`. The returned `userToken` becomes the `x-access-token`.

### 5.3 Device registration for push — `FirebaseTokenManager`

On `onNewToken` / login, `storeTokenAndSubscribeToNotifications()`:

1. `FirebaseMessaging.subscribeToTopic("fcmProdAll")` (the `notifTopic` build value).
2. `POST v1/users/subscribe_device` with `DeviceTokenRequestDTO{deviceToken, deviceType, osVersion, appVersion}` where `appVersion = "0.1308.0-1140"`, `osVersion = Build.VERSION.RELEASE` (deviceType defaults to android).
3. `POST v1/users/unsubscribe_device` on logout.

User's own fetches: `GET /v1/user/{userId}?include=plus,protect,safetyProfile,subscription`, `GET /v1/users/{userId}/stats`, `GET /v1/users/{userId}/subscription_digest`, `GET /v1/users/batch_public` (verified reachable unauthenticated, returned `{"results":[]}`).

---

## 6. WebSocket (`wss://data.sp0n.io/websocket`)

### 6.1 Connection setup — `sp0n.citizen.data.net.sockets.SocketConnection`

```java
this.client = new u9h(new URI(url()),          // wss://data.sp0n.io/websocket
    v1a.m21177b(new Pair("x-access-token", token)),  // HTTP header map
    new h75());                                 // WebSocket draft
SSLContext sSLContext = SSLContext.getInstance("TLS");
sSLContext.init(null, null, null);
client.setSocket(sSLContext.getSocketFactory().createSocket());
client.connect();
```

* Auth = `x-access-token` **handshake header**, same token as REST.
* Two token flavors: `connectWithUserToken()` (session token) or `connectWithGenericToken()` — a self-issued **anonymous JWT**: `Jwts.builder().setHeaderParam("typ","JWT").setSubject("test").signWith(HS256, base64(clientKey)).compact()` where `clientKey` is the embedded `b384d0cf…` string. `[CODE]`
  * `[VERIFIED]` Live test: handshake **without** any `x-access-token` → `HTTP/1.1 101 Switching Protocols`, socket stays open. Handshake **with** my reconstruction of the generic JWT → `403 Forbidden` (all claim variants tried). So anonymous connections are accepted, but token validation is strict when a token *is* presented; the in-app generic-JWT path appears either legacy or its claims differ from what I reconstructed. `[INFERRED]` that the generic token once worked.
* Keep-alive: WebSocket **ping every 20 s** (`keepAliveTimer`, `client.sendPing()`).
* Reconnect: on unplanned close, exponential backoff `2^min(3, attempts)` **seconds** (2→4→8 s cap), timer-scheduled; only while app is foreground (`appStateContainer`); counters reset on open.
* On reconnect, `onConnected` → `flush()` re-sends every queued *and* running (subscription) request — i.e., subscriptions are automatically re-issued.
* App-background → `disconnect()`; reconnect occurs on foreground/auth-state change.

### 6.2 Wire protocol

Client → server (from `SocketConnection2.write` / `SocketConnectionFlow.write`):

```json
{"method": "<methodName>", "value": <argument-or-omitted>}
```

Server → client envelope (`SocketUnparsedMessages` / `SocketMessageDTO` / `SocketPayloadDTO`):

```json
{"messages":[{"type":"<type>",
              "payload":{"namespace":"...", "channel":"...", "value":{...}}}]}
```

Error frame (verified live): `{"messages":[{"type":"error","payload":"auth required"}]}`.

### 6.3 Methods implemented by the app

| Method | Args | Producer | Purpose |
|---|---|---|---|
| `subscribeIncidentChat` / `unsubscribeIncidentChat` | `{incidentId}` | `livechat/LiveChatSocketApiImpl` | live incident chat feed |
| `subscribeDirectMessage` | none | `api/social/SocialSocketApiImpl` | friend DMs |
| `ackDirectMessage`, `ackGroupMessage`, `sendIsTyping` | DTOs | same | DM acks/typing |
| `subscribeAgentChatFeed` / `unsubscribeAgentChatFeed` | `{sessionId}` | `data/premium/protect/AgentEventSocketApiImpl` | Protect agent chat |
| `subscribeProtectFeed` | `{sessionId}` | `data/premium/protect/ProtectAgentSocketApiImpl` | Protect session events (`protectMessageEvent`: `AGENT_UPDATE`, `SESSION_ENDED`, `NEW_USER_RECORD`, `OUTGOING_CALL_UPDATE`, `TRIGGERED_INTERACTIVE_ELEMENT`) |

Inbound `type` values seen in code: `newMessage`, `newGroupMessage`, `protectMessageEvent`, `error`.

`[VERIFIED]` Anonymous socket accepts the connection but every method (`subscribeIncidentChat`, `subscribeDirectMessage`, `bogus`) replies `auth required` — **the WS is not usable without a real account token**, and notably *no socket method exists for the incident feed itself* (incident push is FCM/tile-based).

---

## 7. Push notifications (real-time incident alerts)

`sp0n.citizen.services.CitizenFirebaseMessagingService` (manifest, FCM):

* Delegates Iterable payloads to `IterableFirebaseMessagingService`, then `MessageReceivedUseCase` (`p000.paa`) dispatches on `data["type"]` — all pushes are **data messages**, mostly high-priority (`Silent`/`Silent-User-Location-Update` exempt from the high-priority check).
* `Silent-User-Location-Update` → starts `LocationGetService` (foreground service → server-side geo-targeted alerts via `POST v1/users/{userId}/state`, `LocationApi`).
* Other types → `ShowNotificationUseCase` (`p000.soe`) posts the system notification; payloads carry `incidentId`, `streamId`, `triggerType`, `targetingType` (`Global`/`Geography` → `markIncidentAsGlobal`), `directMessageId`, etc.
* Push `type` taxonomy (`sp0n.citizen.notifications.PushType`, `networkValue`):
  `GeoPush`, `Citywide`, `NearbyVerified`, `RichContent`, `Silent`, `Silent-User-Location-Update`, `ValidatedVideo`, `RelationshipRequested/-Reminder/-Confirmed`, `NewUserJoined`, `chatRemoved`, `DMSent`, `GroupDMSent`, `FriendNearby`, `openInWebview`, `openDeeplink`, `incident_chat`, `messageSummaryNotification`, `openPod`, `StatusDMSent`, `educationModal`, `openFriendDetail`, `foam`, `protectSession`, `premium_invite`, `FamilyPlanInvite`, `FamilyPlanChangeProfile`, `getHelpDemo`, `appSettings`, `app247Settings`, `emergencyContacts`, `paywall`, `protectSettings`, `agentChatNotif`, `shield`, `offender_detail`, `offender_map_layer`, `safety-center`, `expiring_trial`, `newsTab`, `safetyNetworkInvite`, `safetyNetworkUpgrade`, `completePremiumSetup`, `promo_offer`, `IGLRejected`, `badges`, `video24HourRecap`, `centinel_education`, `BroadcasterTransactionPayout`, `worldCupHub`, `newsBriefing`.
* Geo-targeting model: devices continuously upload location (`LocationUploadService`, `POST v1/users/{userId}/state`), and the backend pushes `NearbyVerified`/`GeoPush`/`Citywide` to devices inside the incident's broadcast radius (`broadcastRules.distanceMeters`, `deadline` fields present in incident payloads).
* Device registration: `POST v1/users/subscribe_device` + FCM topic `fcmProdAll` (see §5.3).

**Implication:** push is the primary real-time incident channel but is unreachable for third parties — it requires a registered device token + authenticated user, and payloads are per-device targeting decisions made server-side.

---

## 8. Incident data flow — how the app fetches incidents

### 8.1 Bootstrap / map discovery chain (home screen)

```
locate device
  → GET v1|v2/homescreen/status?lat&long            (SafetyHomeStatusRepository)
      → serviceAreaCode, inServiceArea, locationName, sonar, map config, offender count
  → map pan/zoom → GET v1/homescreen/mapExplore?lowerLongitude&lowerLatitude&upperLongitude&upperLatitude
      → {serviceAreas:[...]}                        (SafetyHomeServiceAreaRepository)
  → for each serviceAreaCode:
      GET v3/homescreen/mapIncidents?serviceAreaCode=<code>&active_definition=state_based
                                                  (SafetyHomeIncidentsRepository.getIncidentsInArea)
      → {incidents:[IncidentMarkerStub…], inactiveIncidents:[…], incidentTimeFrame:int}
  → Mapbox vector source "all_incidents": tiles [https://data.sp0n.io/v1/tile/incidents/{x}/{y}/{z}.pbf]
      (MapFiltersV2Config.incidentTileURL — remotely configurable via variable settings)
```

`loadServiceAreasForMapBounds` is driven by map movement and by `status` changes (`serviceAreas` StateFlow); each new service-area set triggers `loadIncidentsForServiceArea`. There is no client-side timer loop for `mapIncidents` — freshness comes from (a) tile refetches as the map moves/zooms, (b) status reload on location change / foreground (`loadStatusForUserLocationIfNeeded(location, refresh)`), and (c) FCM pushes prompting the user back into the app. `[CODE]` — no periodic feed poller was found for the map feed; `incidentPollingInterval` (variable setting) is used by `BroadcastRepository` for broadcast/live-stream state, not the incident list.

#### 8.1.1 Map tile refresh mechanics — does the app poll? `[VERIFIED — static analysis + live headers]`

**No application-level timer exists for map incident tiles.** Exhaustive search of `safetyhome/` and `data/safetyhome4/` finds no `delay()`, `Timer`, `postDelayed`, ticker flow, or `while(true)` loop feeding tile requests. The map is a `com.mapbox.maps.MapView` (Mapbox Maps SDK v10 — **not** MapLibre; base class `p000/a01.java` creates the `MapView`).

The incident layer is vector source **`all_incidents`** whose `tiles` property is set to a single URL built by `C6655y.m19411r(set, iv9, zoom)`:

```
{incidentTileURL}?incident_category=<cat>…&incident_created_at_gte=<ISO>
                 &incident_created_at_lte=<ISO>&limit=<n>
                 &with_lifecycle_state=true&active_definition=state_based
```

* `incident_category` — one entry per active category filter (empty = all).
* `incident_created_at_gte/lte` — **only present when a date filter is active**; a calendar-day window (local midnight→midnight via `OffsetDateTime`).
* `limit` — per-zoom cap from `MapFiltersV2Config.limitForZoom(zoom)`; recomputed when the camera's zoom band changes.
* `with_lifecycle_state=true&active_definition=state_based` — always appended by the app. Verified live to be a **no-op** on tile content (identical bytes with/without); `limit` and `incident_category` do change tile content.

**URL application — every call site of the update function `t38.m19806s(url)` is enumerated:**

| Trigger | Site | Effect |
|---|---|---|
| Initial style build | `C6649s` ≈l.2907/3802 (`new ptg("all_incidents")` + `map.put("tiles", …)` + `mo413a(style)`) | source created with the URL |
| Camera-move end | `C6649s` l.797, l.869, l.942 — inside the map-location emitters that also fire `loadServiceAreasForMapBounds`, `onMapMoved`, `panned_homescreen_map` analytics | URL rebuilt with current zoom → `m19806s` |
| Filter-state change | `C6654x` l.125 — flow collector on `Pair<Set<category>, dateFilter>` | URL rebuilt → `m19806s` |

`m19806s` (`p000/t38.java:769`) **early-returns if the URL string is unchanged**; otherwise it calls `MapboxStyleManager.setStyleSourceProperty("all_incidents", "tiles", [url])` (`p000/n1f.java:132` → `NativeMapImpl`/`StyleManager` native call), which re-requests all visible tiles for the new URL.

**Freshness floor — HTTP caching `[VERIFIED live]`:** incident tile responses carry `Cache-Control: public, max-age=60` through Varnish/Google CDN. The Mapbox native tile loader honors HTTP expiry: tiles past `max-age` are re-requested (with revalidation) during its tile-update passes. So while the map is visible, viewport tiles are effectively re-fetched on ~60-second expiry — a **cache-driven refresh, not an app timer**. There is no explicit cache-buster, no `volatile`/`refreshInterval` source option, and no `reloadSource`/`invalidateTile` call in the app.

**Aging is also client-side:** layer filters embed `System.currentTimeMillis()` literals (`C6649s` l.3702/3823 via `t38.m19796n`) and `maxAgeInHoursByZoomLevel` thresholds (l.3540–3547), so over-age incidents are hidden by style expressions even if still present in the tile.

**Not refresh triggers (verified negative):**

* **FCM** — `CitizenFirebaseMessagingService.onMessageReceived` → `MessageReceivedUseCase` (`p000/paa.m16188a`) touches `BroadcastRepository` (only while broadcasting), `RelationshipRepository.refreshFriendsData`, `IncidentsRepository.markIncidentAsGlobal`, `EducationRepository` — **nothing map-related**.
* **WebSocket** — chat/Protect subscriptions only (§6); no incident-map stream.
* **`refreshLocationJob`** (`SafetyHomeMapRepository:287`, called from `C6649s:3242`, `C6655y:1711`) — re-subscribes to the fused-location provider; unrelated to tiles.
* **`incidentPollingInterval`** (default **15 s**, `PollingKeys` → `IncidentPollingValue`) — consumed **only** by `BroadcastRepository` for active broadcast/video sessions (`incidentPollingValue.getIncidentPolling() * 1000` around `broadcastApi.getBroadcastInfo`). It does **not** drive the map. `[VERIFIED — only consumer]`

**Bottom line:** the official map does **not poll** on a fixed interval. Tiles are pulled when (1) the camera settles in a new zoom band or viewport, (2) the filter state changes the URL, or (3) a cached tile passes its 60-second `max-age` during the render loop. `[VERIFIED]` that no faster mechanism exists in the app code; the exact idle-refresh cadence depends on Mapbox's render/update scheduling (inference: continuous rendering → ~60 s effective freshness; no explicit timer either way).

### 8.2 Incident detail — `sp0n.citizen.data.incident.IncidentRetrofitApi`

| Method | Path | Params | Response |
|---|---|---|---|
| GET | `v1/incident/{incidentId}?with_stats=true&with_facepile=true` | path | `IncidentDTO` |
| GET | `v2/incident/{incidentId}?with_stats=true&with_radio_clips=` | path+query | `IncidentV2DTO` |
| GET | `v3/incident/{incidentId}` | `with_lifecycle_state`, `active_definition` | `IncidentV2DTO` |
| GET | `v1/incidents/batch?with_stats=true&with_facepile=true&with_radio_clips=true&incident_ids=<csv>` | query | `List<IncidentDTO>` |
| GET | `v1/incidents/{id}/content?with_stats=true&blocked=false` | path | `List<IncidentContentResponseDTO>` |
| GET | `v1/incidents/{id}/map_sources` | path | `IncidentMapSources` |
| GET | `v1/incidents/{id}/related_incidents` | path | `{relatedIncidents:[ids]}` |
| GET | `v2/incidents/news_briefing?service_area=` | query | `NewsBriefingResponseDTO` |
| GET/POST/DELETE | `v1/incidents/{id}/follow` | — | follow state |
| POST | `v1/incident/{id}/stats/views` `/stats/shares` `/stats/{reaction}` | body DTO | Unit |
| POST | `v1/video_stream/{id}/view` `/stats/views` `/report` `/remove`; `v2/video_stream/{id}/user_verification` | — | Unit |

`IncidentsRepository` caches `lastFetchedIncidentsById`/`lastFetchedIncidentDetailsById` in memory, invalidates per-incident, and dedupes live-video views.

### 8.3 Incident vector tiles (primary geographic feed)

* `GET /v1/tile/incidents/{x}/{y}/{z}.pbf` — path order literally `{x}/{y}/{z}` per `MapFiltersV2Config.incidentTileURL`. **No auth required.** `[VERIFIED]`
* Content: standard **Mapbox Vector Tile** (`application/x-protobuf`), single layer **`incidents`**, feature properties (decoded from a live tile):

```
categories, category, comment_count, cs, has_vod, incident_id,
incident_score, is_paywalled, latitude, level, lifecycle_state,
longitude, recency_tier, severity, share_count, subcategory,
title, ts, unverified_community_alert, unverified_igl_incident,
view_count
```

  Live example feature (z12 NYC tile, fetched 2026-09-19):
```json
{"incident_id":"-P1vrxK35R7YgOyBYNo2","title":"Report of Vehicle Collision",
 "category":"traffic_related","categories":"traffic_related","subcategory":"collision",
 "latitude":40.653793,"longitude":-74.008095,"severity":"yellow",
 "lifecycle_state":"reported","incident_score":0.35734,"level":0,"recency_tier":0,
 "comment_count":0,"share_count":1,"view_count":…,"has_vod":false,
 "is_paywalled":false,"unverified_community_alert":false,"ts":"…","cs":"…"}
```
* Incident IDs are Firebase-push-key style (`-P1vrxK35R7YgOyBYNo2`). `severity` ∈ {`red`,`yellow`,`grey`,…}; `lifecycle_state` ∈ {`reported`, `inactive`, …} (`state_based` is the `active_definition` value used by the app for mapIncidents).
* Tiles are fetched by the Mapbox native tile loader for the `all_incidents` vector source; empty areas return `200` with a 0-byte body. Responses carry `Cache-Control: public, max-age=60` (Varnish/Google CDN) — see §8.1.1 for how this drives refresh. `[VERIFIED live]`
* The app appends query params to the tile URL (`C6655y.m19411r`): `incident_category` (repeatable), `incident_created_at_gte/lte` (ISO-8601, date-filter only), `limit` (per-zoom cap), `with_lifecycle_state=true`, `active_definition=state_based`. Verified live: `limit` and `incident_category` alter tile content; the two static params are no-ops on content.

### 8.4 Feed endpoints

| Endpoint | DTO | Auth? |
|---|---|---|
| `GET v1/homescreen/feed?allTypes=true&lat&long` | `SafetyHomeForYouResponseDTO` | 401 `[VERIFIED]` |
| `GET v2/news/feed?code=` | `NewsResponseDTO` (`{news:[{bucket,isPinned,isBreaking,incident{…}}]}`) | **open** `[VERIFIED]` (120 KB response) |
| `GET v2/incidents/news_briefing?service_area=` | `NewsBriefingResponseDTO` | open, returns 404 `no news briefing found` when absent `[VERIFIED]` |
| `GET v1/friends/feed`, `v1/friends/map`, `v1/friends/map/hydrate` | friends FOAM | 401 |
| `GET v1/trends/neighborhoods/{id}/incidents|details|boundary|graph`, `v1/trends/shs_feed` | trends | open (empty without params) `[VERIFIED]` |
| `GET v1/incidents/social/batch` | social | — |

### 8.5 Chat / comments (per-incident)

`CommentsApi`: `GET v4/incident_chat/history?incident_id&read_since&include_deleted&before_chat_id&limit` (v1 legacy variant) — **both history endpoints return `200` unauthenticated** (`{"messages":[],"pagination":{"hasMore":false,"id":null}}` verified); `GET v1/incident_chat/meta?chat_id` → 401; `POST v1/incident_chat` (send), like/dislike/report endpoints — auth-gated. Live chat over WS via `subscribeIncidentChat` (§6.3).

---

## 9. Full REST endpoint catalog (base `https://data.sp0n.io`)

Auth status: **[OPEN]** = verified 2xx without token; **[401]** = verified rejected without token; **[?]** = code-visible only, not probed.

### Incidents & map
- `GET /v1/incident/{id}` — **[OPEN]**
- `GET /v2/incident/{id}` — **[OPEN]**
- `GET /v3/incident/{id}` — **[OPEN]**
- `GET /v1/incidents/batch?incident_ids=` — **[OPEN]**
- `GET /v1/incidents/{id}/content` — **[OPEN]**
- `GET /v1/incidents/{id}/related_incidents` — **[OPEN]**
- `GET /v1/incidents/{id}/map_sources` — **[OPEN]** (`{"sources":{}}`)
- `GET|POST|DELETE /v1/incidents/{id}/follow` — [?]
- `POST /v1/incident/{id}/stats/views|shares|{reaction}` — [?]
- `GET /v3/homescreen/mapIncidents?serviceAreaCode&active_definition` — **[401]**
- `GET /v1/homescreen/mapExplore?lowerLongitude&lowerLatitude&upperLongitude&upperLatitude` — **[OPEN]**
- `GET /v1/homescreen/status?lat&long` — **[OPEN]**
- `GET /v2/homescreen/status` — **[401]**
- `GET /v1/homescreen/feed?allTypes=true&lat&long` — **[401]**
- `GET /v1/tile/incidents/{x}/{y}/{z}.pbf` — **[OPEN]** (MVT)
- `GET /v1/tile/style/*.json` — map styles (e.g. `citizen-app-light-20250512.json`) [?]
- `GET /v2/news/feed?code=` — **[OPEN]**
- `GET /v2/incidents/news_briefing?service_area=` — **[OPEN]** (404 when none)
- `GET /v1/trends/neighborhoods/{id}/…`, `v1/trends/shs_feed` — **[OPEN]** (empty)
- `POST incidents2/community_alerts/v2`, `…/v2/user_draft`, `…/{incidentId}/user_verification` — community alert submission (`CommunityAlertApi`) [?]

### Geo / safety
- `GET /v1/safety/location?lat&long` — **[OPEN]** (`{"locationName":"Manhattan","address":"10013 3481"}`)
- `GET /v1/safety/location_name?lat&long` — **[OPEN]**
- `GET /v1/safety/location_search?query=` — **[OPEN-ish]** (400 `too short` → input-validated before auth)
- `GET /v1/search` — **[401]**
- `GET /v1/users/nearby`, `/v2/users/nearby` — **[401]**
- `POST /v1/users/{userId}/state` — location upload [?]
- `GET /v1/safety_zones`, `POST /v1/safety_zones`, `GET /v1/safety_zones/template`, `GET /v1/safety_zones/{id}/settings`, `DELETE /v1/safety_zones/{id}`, `POST /v1/ephemeral_safety_zone`, `DELETE /v1/ephemeral_safety_zone/{userId}` (`AlertZonesApi`) [?]

### Auth & user
- `POST /v1/auth/request_code`, `POST /v1.2/auth/validate_code`, `POST /v1/auth/google`, `POST /v1/auth/request_email_code`, `POST /v1/auth/validate_email_code`, `POST /v1/auth/reset_user` — open by design (login) [?]
- `GET /v1/user/{userId}?include=plus,protect,safetyProfile,subscription`, `POST /v1/user/{userId}`, `/archive`, `/phone_number`, `/video_preferences` — [?]
- `GET /v1/users/{userId}/stats|profile|subscription_digest|unread_notification_count`, `POST /v1/users/{userId}/settings`, `GET /v1/users/check_username`, `POST /v1/generate_username`, `GET /v1/users/batch_public` (**[OPEN]**), `POST /v1/users/subscribe_device|unsubscribe_device` — [?]
- `GET /v3/users/{userId}/notifications`, `POST /v1/users/{userId}/notifications/{id}/set_viewed`, `GET /v2/users/{userId}/notification_settings` — [?]

### Social / friends / DMs
- `GET /v1/friends/map`, `/v1/friends/map/hydrate`, `/v1/friends/feed`, `/v1/friends/connected_tab`, `/v1/friends/contacts_on_citizen_count`, `POST /v1/friends/add_friends_tab|invite_group|invite_onboarding|priority`, `POST /v2/friends/invite` — **[401]** (spot-checked)
- `POST /v2/users/{userId}/contacts?return_users=true`, `GET /v2/users/{userId}/suggested_contacts`, `GET /v2/users/{userId}/friends`, `POST /v1/users_relationships`, `/v1/user_contact_relationships`, `/v1/users_relationships/branch`, `GET /v1/users/{userId}/profile?include=stats,friends`, `POST /v1/users/{userId}/active|reports`, `POST /v1/signup/pending`, `POST /v1/referral_rewards[/reset]` — [?]
- `GET|POST /direct_message`, `/direct_message/inbox`, `/direct_message/inbox/hydrate`, `/direct_message/group[/{id}]`, `/direct_message/group/{id}/unread`, `GET /direct_message/{userId}/{friendId}` — [?]
- `GET|POST|DELETE /v1/safety_networks…` (13 endpoints, `SafetyNetworkApi`) — [?]

### Incident chat
- `GET /v4/incident_chat/history`, `GET /v1/incident_chat/history` — **[OPEN]** (verified, `{messages, pagination{hasMore,id}}`)
- `GET /v1/incident_chat/meta` — **[401]**
- `POST /v1/incident_chat`, `POST /v1/incident_chat/{id}/like|dislike|report`, `POST /v1/incident_chat_shadow_ban` — [?]

### Broadcast / video / earnings
- `GET /v2/video_stream/{id}`, `GET /v3/users/{id}/video_streams`, `GET /v2/users/{userId}/video_streams`, `POST /v3/video_stream`, `POST /v5/video_stream`, `GET /v1/video_streams/monthly_counts`, `GET /v1/video_stream/{id}/earnings`, `POST /v1/video_stream/{id}/view|remove|report|stats/views`, `POST /v2/video_stream/{id}/user_verification`, `GET /v1/incident/{id}/stream_badges`, `GET /v1/user/{id}/payment_summary|balance|unit_economics`, `POST /v1/user/{id}/cashout` (`BroadcastApi`,`VideoApi`) — [?]

### Protect (premium) / purchase
- `POST /v1/protect/session`, `GET|DELETE /v1/protect/session/{id}`, `POST /v1/protect/session/{id}/records|video_control`, `POST /v1/protect/safety_profile`, `GET /v1/protect/impact_statistics`, `POST /v1/protect/family/branch`, `POST /v1/protect/setup_reminder`, `POST /v1/protect/hardware/ready`, `POST /v2/protect/agent_chat[/{sessionId}][/lifecycle|/records|/add_ons[/shield/records]]`, `DELETE /v2/protect/agent_chat/{sessionId}` — [?]
- `POST /v1/purchase`, `/v1/purchase/product_change`, `POST /v1|v2/android/validate_purchase[_v2]|validate_subscription[_v2]` — [?]

### Misc
- `GET /v1/variable_settings` — **[401]**; `GET /v1/variable_settings_anonymous` — **[OPEN]** (≈179 KB experiment/feature config; source of `incidentTileURL`, `incidentPollingInterval`, etc.)
- `GET /v3/education_modals`, `POST /v1/education_modals/view` — **[401]**
- `GET /v1/report/categories`, `POST /v1/report` — **[401]**
- `GET /v1/offenders/{id}`, `POST /v1/offenders/{id}/view` — [?]
- `POST /v1/magic_qr_codes/execution`, `POST /v1/debug/log` (SlackApi), `GET /v2/platforms/android/gmp/…` — [?]
- `GET /v1/doc/features.html` — 404 `[VERIFIED]`

---

## 10. Unauthenticated access assessment (live-verified, read-only)

| Request | Result |
|---|---|
| `GET /healthz` | 200 `OK` |
| `GET /v1/variable_settings_anonymous` | 200 — 178,690 B of experiment/flag JSON |
| `GET /v1/homescreen/mapExplore?…bbox…` | 200 `{"serviceAreas":["nyc","us-nj-newark",…]}` |
| `GET /v1/homescreen/status?lat&long` | 200 — `serviceAreaCode`, `locationName`, `sonar`, `map`, `offender`, `pastXHourIncidentsInServiceArea` |
| `GET /v1/tile/incidents/{x}/{y}/{z}.pbf` | 200 `application/x-protobuf` — real MVT data (0 B when empty) |
| `GET /v1|v2|v3/incident/{id}` | 200 — full detail JSON |
| `GET /v1/incidents/batch?incident_ids=` | 200 |
| `GET /v1/incidents/{id}/content` | 200 (`[]`) |
| `GET /v1/incidents/{id}/related_incidents` | 200 |
| `GET /v1/incidents/{id}/map_sources` | 200 |
| `GET /v2/news/feed` | 200 — 120 KB feed |
| `GET /v1/safety/location`, `location_name` | 200 |
| `GET /v1/safety/location_search?query=` | input validation before auth (400 `too short`) |
| `GET /v1/users/batch_public` | 200 `{"results":[]}` |
| `GET /v1|v4/incident_chat/history?incident_id=` | 200 `{messages, pagination{hasMore,id}}` |
| `GET /v1/trends/…` | 200 (empty) |
| `GET /v3/homescreen/mapIncidents` | **401** `invalid token supplied` |
| `GET /v2/homescreen/status` | **401** `access token missing` |
| `GET /v1/homescreen/feed` | **401** |
| `GET /v1/search`, `/v1/report/categories`, `/v1/variable_settings`, `/v3/education_modals`, `/v1/users/nearby`, `/v1/friends/map` | **401** |
| `WSS /websocket` no headers | **101 accepted**, then `auth required` on any method |
| `WSS /websocket` + reconstructed generic JWT | **403** |

**Conclusion:** the incident read-path (tiles + incident detail + related + batch + map sources + news feed + service-area discovery + safety geocoding + status v1) is completely unauthenticated. Personalized surfaces (home feed v2/v3, mapIncidents aggregation, friends, notifications, chat, reporting, purchases) require a real `userToken`. The WebSocket accepts anonymous TCP connections but refuses all methods without auth.

---

## 11. Key response schemas (from DTOs + live samples)

`SafetyHomeStatusV2ResponseDTO` — `{inServiceArea, serviceAreaCode, serviceAreaName, locationName, nearby{userCount,displayUserCount,incidents[]}, sonar{color,radiusMeters}, map{zoomLevel,nearbyRadius,communityRadius}, offender{offenderCount}, pastXHourIncidentsInServiceArea}`

`SafetyHomeMapIncidentsResponseDTO` — `{incidents:[IncidentMarkerStub], inactiveIncidents:[…], incidentTimeFrame:int}`

`IncidentMarkerStubDTO` — `{incidentId, title, category, subcategory, latitude, longitude, level, severity(_severity), lifecycleState, lifecycleStateSubtitle, recencyTier, score, commentCount, shareCount, viewCount, isTrending, updatedAt, magicMomentsTag, helicopter, shsVideo}`

`IncidentV2DTO` — `{incidentId, title, category, subcategory, location, locationDetails{coordinates,formattedAddress,streetAddress,neighborhood,city,state{name,code},serviceAreaCode,police}, position{lat,long}, neighborhood, level, closed, confirmed, chatBlocked, isPaywalled, status, stats, agency, agencyDTO…, broadcastRules{distanceMeters,deadline}, carousel[], modules[], updates[], summaryCards[], nib, nearbyCommunityMembers, unverifiedCommunityAlert, webviewContent, homescreenMapThumbnail, recencyTier, lifecycleState, lifecycleStateSubtitle, incidentSource}`

`IncidentDTO` (v1) — `{key, title, raw, rawLocation, address, location, locationDetails, cityCode, neighborhood, latitude, longitude, ll[], ts, cs, level, hasVod, transcriber, externalSyncVersion, broadcastRules,…}` (live-verified superset)

`CodeVerificationResponseDTO` — `{userToken, uid, registered}`

MVT `incidents` layer properties — see §8.3.

Socket envelopes — see §6.2.

---

## 12. What this means for a third-party incident feed

**Feasible today, no credentials:**
1. Choose a coverage bbox → convert to z-tiles (z≈12 gives city-block granularity; the app fetches whatever zoom the map is at).
2. `GET /v1/tile/incidents/{x}/{y}/{z}.pbf` per tile, decode MVT layer `incidents` → marker-level feed (id, title, category, lat/long, severity, lifecycle_state, score, ts/cs).
3. Hydrate interesting incidents via `GET /v3/incident/{id}` (or `v1`/`v2`), optionally `related_incidents`, `content`, `map_sources`, `batch`.
4. Poll tiles on an interval for updates — no push/stream exists for third parties. `cs`/`ts`/`externalSyncVersion` fields make change-detection cheap.
5. `GET /v1/homescreen/mapExplore` (bbox→serviceAreaCodes) and `/v1/homescreen/status` (lat/long→service area, nearby stats) provide geographic indexing.

**Not feasible without an account:**
* `mapIncidents` aggregation, personalized feed, WebSocket subscriptions (`auth required`), FCM alerting, chat history, reporting/community alerts, anything user-scoped.

**Caveats / hypotheses:**
* Tile freshness window is server-defined (`incidentTimeFrame`); how far back inactive incidents persist is `[INFERRED]` (tile showed `reported`+`inactive` states).
* Whether tile requests require the `Vigilante` UA/`build-number` headers is untested both ways — requests succeeded *with* them; a bare `curl` without app headers was not exhaustively tested on every path (tiles and incident GETs did not appear to check, but sending the app-like headers is the safer bet). `[INFERRED]`
* Rate limits unknown — no 429s observed during light probing.
* The auth wall on `v3/mapIncidents` + `v2/status` vs. open v1 endpoints suggests the read surface is deliberately public-ish (or inconsistently locked down); it could be restricted at any time.
* Anonymous-WS acceptance might be for pre-auth handshake phases (app connects socket early during onboarding) — every method still requires auth, so it is not a data source.
* `userToken` TTL/rotation unknown; no refresh endpoint exists in-app, so tokens are presumably long-lived.

## 13. Source references (decompiled tree `jadx-out/sources/`)

* `sp0n/citizen/core/api/retrofit/NetworkingModule.java` — OkHttp/Retrofit builders, headers
* `sp0n/citizen/api/BuildConfigModule.java`, `data/common/BuildConfigInfo.java`, `data/common/UrlHelper.java` — hosts/config
* `sp0n/citizen/data/common/SessionManager.java` — token storage
* `sp0n/citizen/data/net/sockets/{SocketConnection,SocketConnection2,SocketConnectionFlow}.java` — WS client, reconnect, generic JWT
* `sp0n/citizen/data/social/SocialSocketApi.java` + `api/social/SocialSocketApiImpl.java`, `livechat/LiveChatSocketApiImpl.java`, `data/premium/protect/{AgentEventSocketApiImpl,ProtectAgentSocketApiImpl}.java` — WS methods
* `sp0n/citizen/services/CitizenFirebaseMessagingService.java`, `p000/paa.java` (MessageReceivedUseCase), `p000/soe.java` (ShowNotificationUseCase), `sp0n/citizen/notifications/PushType.java`, `data/user/FirebaseTokenManager.java` — push pipeline
* `sp0n/citizen/data/incident/IncidentRetrofitApi.java`, `data/incident/IncidentsRepository.java` — incident REST + caching
* `sp0n/citizen/data/safetyhome4/{SafetyHomeApi2,SafetyHomeStatusRepository,SafetyHomeServiceAreaRepository,SafetyHomeIncidentsRepository,SafetyHomeFeedRepository}.java` — home/map fetch chain
* `sp0n/citizen/data/variablesettings/MapFiltersV2Config.java` — incidentTileURL default
* `sp0n/citizen/api/onboarding/OnBoardingApiRetrofit.java`, `data/onboarding/dto/*` — auth
* `sp0n/citizen/data/user/UserRetrofitApi.java`, `data/notifications/RetrofitNotificationsApi.java`, `data/comments/CommentsApi.java`, `data/news/NewsApi.java`, `data/neighborhood/NeighborhoodApi.java`, `data/location/LocationApi.java`, `data/social/{SocialApiRetrofit,SafetyNetworkApi}.java`, `data/broadcast/BroadcastApi.java`, `data/dms/{MessageApi,ProtectSessionApi}.java`, `api/AlertZonesApi.java`, `data/offender/OffendersAPI.java`, `data/incident/{ReportIncidentApi,CommunityAlertApi}.java` — remaining endpoint interfaces
* `apktool-out/AndroidManifest.xml`, `res/xml/network_security_config.xml`, `res/values/strings.xml` — manifest, pinning (none), hosts/keys
