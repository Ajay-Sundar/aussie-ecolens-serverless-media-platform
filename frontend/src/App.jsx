import { useEffect, useMemo, useRef, useState } from "react";
import "./App.css";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;
const COGNITO_DOMAIN = import.meta.env.VITE_COGNITO_DOMAIN;
const COGNITO_CLIENT_ID = import.meta.env.VITE_COGNITO_CLIENT_ID;
const REDIRECT_URI = import.meta.env.VITE_COGNITO_REDIRECT_URI;

const SESSION_KEYS = {
  idToken: "aussie_ecolens_id_token",
  accessToken: "aussie_ecolens_access_token",
  refreshToken: "aussie_ecolens_refresh_token",
  pkceVerifier: "aussie_ecolens_pkce_verifier",
  oauthState: "aussie_ecolens_oauth_state",
};

const NAV_ITEMS = [
  { id: "dashboard", label: "Overview", icon: "▣" },
  { id: "upload", label: "Upload Media", icon: "⇧" },
  { id: "search", label: "Search Library", icon: "⌕" },
  { id: "thumbnail", label: "Thumbnail Lookup", icon: "▤" },
  { id: "reverse", label: "Reverse Search", icon: "◎" },
  { id: "tags", label: "Manage Tags", icon: "⟐" },
  { id: "delete", label: "Delete Files", icon: "⌧" },
  { id: "evidence", label: "Evidence", icon: "✦" },
];

function base64UrlEncode(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = "";

  bytes.forEach((byte) => {
    binary += String.fromCharCode(byte);
  });

  return btoa(binary)
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

function randomString(length = 64) {
  const possible =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~";
  const values = crypto.getRandomValues(new Uint8Array(length));

  return Array.from(values)
    .map((value) => possible[value % possible.length])
    .join("");
}

async function createCodeChallenge(verifier) {
  const encoded = new TextEncoder().encode(verifier);
  const digest = await crypto.subtle.digest("SHA-256", encoded);

  return base64UrlEncode(digest);
}

async function readResponseBody(response) {
  const text = await response.text();

  try {
    return text ? JSON.parse(text) : {};
  } catch {
    return { raw: text };
  }
}

async function calculateFileChecksum(file) {
  // Read the selected file into memory.
  const fileBuffer = await file.arrayBuffer();

  // Calculate SHA-256 using the browser Web Crypto API.
  const hashBuffer = await crypto.subtle.digest("SHA-256", fileBuffer);

  // Convert hash bytes into a readable hex string.
  const hashArray = Array.from(new Uint8Array(hashBuffer));

  return hashArray
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

function PrettyJson({ data }) {
  if (!data) return null;

  return <pre className="json-box">{JSON.stringify(data, null, 2)}</pre>;
}

function getResultItems(data) {
  if (!data) return [];

  return (
    data.items ||
    data.results ||
    data.files ||
    data.media ||
    data.matches ||
    data.urls ||
    data.body?.items ||
    []
  );
}

function MiniMetric({ label, value, helper }) {
  return (
    <article className="mini-metric">
      <span>{label}</span>
      <strong>{value}</strong>
      {helper && <small>{helper}</small>}
    </article>
  );
}

function ResultCards({ data }) {
  const items = getResultItems(data);

  if (!Array.isArray(items) || items.length === 0) {
    return (
      <div className="empty-state">
        <strong>No matching files found</strong>
        <span>Try a different species, tag count, or uploaded query file.</span>
      </div>
    );
  }

  return (
    <div className="result-grid">
      {items.map((item, index) => {
        const fileId = item.file_id || item.id || `result-${index}`;
        const fileType = item.file_type || item.url_type || "media";

        const rawPreviewUrl =
          item.thumbnail_presigned_url ||
          item.thumbnail_https_url ||
          item.presigned_thumbnail_url ||
          item.browser_thumbnail_url ||
          item.thumbnail_url_https ||
          item.preview_url;

        const rawOpenUrl =
          item.original_presigned_url ||
          item.original_https_url ||
          item.presigned_original_url ||
          item.browser_original_url ||
          item.original_url_https ||
          item.full_url ||
          item.download_url;

        const previewUrl =
          typeof rawPreviewUrl === "string" && rawPreviewUrl.startsWith("http")
            ? rawPreviewUrl
            : null;

        const openUrl =
          typeof rawOpenUrl === "string" && rawOpenUrl.startsWith("http")
            ? rawOpenUrl
            : null;

        const storedThumbnailUrl =
          item.thumbnail_url || item.result_url || item.thumbnailUrl;

        const storedOriginalUrl =
          item.original_url || item.originalUrl || item.url || item.result_url;

        const isImage = fileType === "image" || item.url_type === "thumbnail";
        const isVideo = fileType === "video" || item.url_type === "video";

        return (
          <article className="result-card" key={`${fileId}-${index}`}>
            <div className="result-card-preview">
              {previewUrl && isImage ? (
                <a href={openUrl || previewUrl} target="_blank" rel="noreferrer">
                  <img src={previewUrl} alt={`Preview for ${fileId}`} />
                </a>
              ) : isVideo ? (
                <div className="media-placeholder">
                  <span>VIDEO</span>
                  <strong>Video result available</strong>
                </div>
              ) : (
                <div className="media-placeholder">
                  <span>MEDIA</span>
                  <strong>Preview unavailable</strong>
                </div>
              )}
            </div>

            <div className="result-card-body">
              <div className="result-head">
                <div>
                  <strong>{item.filename || `Result ${index + 1}`}</strong>
                  <small>{fileId}</small>
                </div>
                <span className="type-pill">{fileType}</span>
              </div>

              {item.status && <p>Status: {item.status}</p>}

              {item.tags && (
                <code className="tag-code">{JSON.stringify(item.tags)}</code>
              )}

              {openUrl ? (
                <a
                  className="secondary-action"
                  href={openUrl}
                  target="_blank"
                  rel="noreferrer"
                >
                  Open full file
                </a>
              ) : (
                <button className="disabled-button" disabled>
                  Full file link unavailable
                </button>
              )}

              <details>
                <summary>Stored URLs</summary>
                {storedThumbnailUrl && (
                  <small>
                    Thumbnail: <span>{storedThumbnailUrl}</span>
                  </small>
                )}
                {storedOriginalUrl && (
                  <small>
                    Original: <span>{storedOriginalUrl}</span>
                  </small>
                )}
              </details>
            </div>
          </article>
        );
      })}
    </div>
  );
}

function App() {
  const [activeModule, setActiveModule] = useState("dashboard");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  const [idToken, setIdToken] = useState(
    sessionStorage.getItem(SESSION_KEYS.idToken) || ""
  );
  const [authMessage, setAuthMessage] = useState("");
  const [loadingAuth, setLoadingAuth] = useState(false);

  const [statusMessage, setStatusMessage] = useState("");
  const [statusType, setStatusType] = useState("info");

  const [tagSummary, setTagSummary] = useState(null);
  const [searchResult, setSearchResult] = useState(null);
  const [uploadResult, setUploadResult] = useState(null);
  const [uploadStatusResult, setUploadStatusResult] = useState(null);
  const [isUploading, setIsUploading] = useState(false);
  const [thumbnailResult, setThumbnailResult] = useState(null);
  const [queryUploadResult, setQueryUploadResult] = useState(null);
  const [bulkTagResult, setBulkTagResult] = useState(null);
  const [deleteResult, setDeleteResult] = useState(null);

  const uploadInputRef = useRef(null);

  const [selectedUploadFile, setSelectedUploadFile] = useState(null);
  const [selectedQueryFile, setSelectedQueryFile] = useState(null);
  const [latestUploadFileId, setLatestUploadFileId] = useState("");

  const [searchMode, setSearchMode] = useState("species");
  const [searchTagsJson, setSearchTagsJson] = useState(
    '{\n  "Canis_familiaris": 1\n}'
  );
  const [speciesName, setSpeciesName] = useState("Canis_familiaris");
  const [thumbnailUrl, setThumbnailUrl] = useState("");
  const [bulkUrls, setBulkUrls] = useState("");
  const [bulkTagsJson, setBulkTagsJson] = useState(
    '{\n  "Manual_reviewed": 1\n}'
  );
  const [bulkOperation, setBulkOperation] = useState("1");
  const [deleteUrls, setDeleteUrls] = useState("");

  const isAuthenticated = Boolean(idToken);

  const maskedToken = useMemo(() => {
    if (!idToken) return "";
    return `${idToken.slice(0, 18)}...${idToken.slice(-10)}`;
  }, [idToken]);

  const dashboardStats = useMemo(() => {
    const totalFiles = tagSummary?.total_files_scanned ?? "—";
    const tagCount = tagSummary?.tag_counts
      ? Object.keys(tagSummary.tag_counts).length
      : "—";

    return {
      totalFiles,
      tagCount,
      providers: "AWS + GCP",
      auth: isAuthenticated ? "Protected" : "Locked",
    };
  }, [tagSummary, isAuthenticated]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");
    const returnedState = params.get("state");

    if (!code) return;

    async function exchangeCodeForTokens() {
      setLoadingAuth(true);
      showStatus("Completing Cognito login...", "info");

      try {
        const expectedState = sessionStorage.getItem(SESSION_KEYS.oauthState);
        const verifier = sessionStorage.getItem(SESSION_KEYS.pkceVerifier);

        if (expectedState && returnedState !== expectedState) {
          throw new Error("OAuth state mismatch. Please sign in again.");
        }

        if (!verifier) {
          throw new Error("Missing PKCE verifier. Please sign in again.");
        }

        const body = new URLSearchParams({
          grant_type: "authorization_code",
          client_id: COGNITO_CLIENT_ID,
          code,
          redirect_uri: REDIRECT_URI,
          code_verifier: verifier,
        });

        const response = await fetch(`${COGNITO_DOMAIN}/oauth2/token`, {
          method: "POST",
          headers: {
            "Content-Type": "application/x-www-form-urlencoded",
          },
          body,
        });

        const tokenData = await readResponseBody(response);

        if (!response.ok) {
          throw new Error(
            tokenData.error_description ||
              tokenData.error ||
              "Token exchange failed."
          );
        }

        sessionStorage.setItem(SESSION_KEYS.idToken, tokenData.id_token);
        sessionStorage.setItem(SESSION_KEYS.accessToken, tokenData.access_token);

        if (tokenData.refresh_token) {
          sessionStorage.setItem(
            SESSION_KEYS.refreshToken,
            tokenData.refresh_token
          );
        }

        sessionStorage.removeItem(SESSION_KEYS.pkceVerifier);
        sessionStorage.removeItem(SESSION_KEYS.oauthState);

        setIdToken(tokenData.id_token);
        setAuthMessage("Signed in successfully.");
        showStatus("Signed in successfully.", "success");

        window.history.replaceState({}, document.title, window.location.pathname);
      } catch (error) {
        setAuthMessage(error.message);
        showStatus(error.message, "error");
      } finally {
        setLoadingAuth(false);
      }
    }

    exchangeCodeForTokens();
  }, []);

  function showStatus(message, type = "info") {
    setStatusMessage(message);
    setStatusType(type);
  }

  function clearSelectedUploadFile() {
    setSelectedUploadFile(null);

    if (uploadInputRef.current) {
      uploadInputRef.current.value = "";
    }
  }

  async function apiRequest(path, options = {}) {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${idToken}`,
        ...(options.headers || {}),
      },
    });

    const data = await readResponseBody(response);

    if (!response.ok) {
      throw new Error(
        data.message ||
          data.error ||
          data.raw ||
          `Request failed with HTTP ${response.status}`
      );
    }

    return data;
  }

  async function enrichResultUrls(data) {
    const items = getResultItems(data);

    if (!Array.isArray(items) || items.length === 0) {
      return data;
    }

    const enrichedItems = await Promise.all(
      items.map(async (item) => {
        if (!item.file_id) return item;

        try {
          const urls = await apiRequest(`/media/${item.file_id}/urls`);

          return {
            ...item,
            original_presigned_url:
              urls.original_presigned_url ||
              urls.original_url_presigned ||
              urls.presigned_original_url ||
              urls.original_https_url,
            thumbnail_presigned_url:
              urls.thumbnail_presigned_url ||
              urls.thumbnail_url_presigned ||
              urls.presigned_thumbnail_url ||
              urls.thumbnail_https_url,
          };
        } catch {
          return item;
        }
      })
    );

    return {
      ...data,
      items: enrichedItems,
    };
  }

  async function login() {
    const verifier = randomString(96);
    const challenge = await createCodeChallenge(verifier);
    const state = randomString(32);

    sessionStorage.setItem(SESSION_KEYS.pkceVerifier, verifier);
    sessionStorage.setItem(SESSION_KEYS.oauthState, state);

    const params = new URLSearchParams({
      client_id: COGNITO_CLIENT_ID,
      response_type: "code",
      scope: "openid email",
      redirect_uri: REDIRECT_URI,
      code_challenge_method: "S256",
      code_challenge: challenge,
      state,
    });

    window.location.href = `${COGNITO_DOMAIN}/login?${params.toString()}`;
  }

  function logout() {
    sessionStorage.clear();
    setIdToken("");

    const params = new URLSearchParams({
      client_id: COGNITO_CLIENT_ID,
      logout_uri: REDIRECT_URI,
    });

    window.location.href = `${COGNITO_DOMAIN}/logout?${params.toString()}`;
  }

  async function loadTagSummary() {
    try {
      showStatus("Loading tag summary...", "info");
      const data = await apiRequest("/media/tag-summary");
      setTagSummary(data);
      showStatus("Tag summary loaded.", "success");
    } catch (error) {
      showStatus(error.message, "error");
    }
  }

  async function searchBySpecies() {
    try {
      showStatus(`Searching for ${speciesName}...`, "info");

      const encodedSpecies = encodeURIComponent(speciesName.trim());
      const data = await apiRequest(`/media/by-tag/${encodedSpecies}`);
      const enrichedData = await enrichResultUrls(data);

      setSearchResult(enrichedData);
      showStatus(`Species query completed for "${speciesName}".`, "success");
    } catch (error) {
      showStatus(error.message, "error");
    }
  }

  async function searchByTags() {
    try {
      showStatus("Running tag-count query...", "info");
      const tags = JSON.parse(searchTagsJson);

      const data = await apiRequest("/media/search-by-tags", {
        method: "POST",
        body: JSON.stringify({ tags }),
      });

      const enrichedData = await enrichResultUrls(data);

      setSearchResult(enrichedData);
      showStatus("Tag-count query completed.", "success");
    } catch (error) {
      showStatus(error.message, "error");
    }
  }

  async function checkLatestUploadStatus() {
    if (!latestUploadFileId) {
      showStatus("No recent upload found to check.", "error");
      return;
    }

    try {
      showStatus("Checking backend processing status...", "info");

      const data = await apiRequest(`/media/${latestUploadFileId}`);
      setUploadStatusResult(data);

      const item = data.item || {};
      const status = item.status || "unknown";

      if (status === "tagged") {
        showStatus(
          "Backend processing complete. File is tagged and searchable.",
          "success"
        );
      } else if (status === "duplicate") {
        showStatus(
          "This file was detected as a duplicate and was not stored again.",
          "success"
        );
      } else {
        showStatus(
          `Backend processing is still in progress. Current status: ${status}`,
          "info"
        );
      }
    } catch (error) {
      showStatus(error.message, "error");
    }
  }

  async function uploadMedia(event) {
    event.preventDefault();

    if (!selectedUploadFile) {
      showStatus("Please choose an image or video file first.", "error");
      return;
    }

    try {
      setIsUploading(true);

      showStatus("Calculating file checksum for duplicate detection...", "info");

      const fileChecksum = await calculateFileChecksum(selectedUploadFile);

      showStatus("Checking whether this file already exists...", "info");

      const uploadInfo = await apiRequest("/generate-upload-url", {
        method: "POST",
        body: JSON.stringify({
          filename: selectedUploadFile.name,
          content_type: selectedUploadFile.type,
          file_checksum: fileChecksum,
        }),
      });

      if (uploadInfo.duplicate || uploadInfo.status === "duplicate") {
        setUploadResult({
          message:
            uploadInfo.message ||
            "Duplicate file detected. Upload skipped because this file already exists.",
          duplicate: true,
          file_checksum: fileChecksum,
          existing_file: uploadInfo.existing_file,
        });

        setUploadStatusResult(null);
        setLatestUploadFileId(uploadInfo.existing_file?.file_id || "");

        showStatus(
          "Duplicate file detected. Upload skipped and the existing file was kept.",
          "success"
        );

        clearSelectedUploadFile();
        return;
      }

      showStatus("Uploading unique file directly to S3...", "info");

      const s3Response = await fetch(uploadInfo.upload_url, {
        method: "PUT",
        headers: {
          "Content-Type": selectedUploadFile.type,
        },
        body: selectedUploadFile,
      });

      if (!s3Response.ok) {
        throw new Error(`S3 upload failed with HTTP ${s3Response.status}`);
      }

      setLatestUploadFileId(uploadInfo.file_id);
      setUploadStatusResult(null);

      setUploadResult({
        message:
          "Upload accepted. The file is in S3 and backend processing has started.",
        processing_note:
          "Wait 30–60 seconds, then click Check processing status to confirm tagging is complete.",
        duplicate: false,
        file_id: uploadInfo.file_id,
        filename: selectedUploadFile.name,
        content_type: selectedUploadFile.type,
        file_type: uploadInfo.file_type,
        bucket: uploadInfo.bucket,
        file_key: uploadInfo.file_key,
        file_checksum: fileChecksum,
        stored_url: `s3://${uploadInfo.bucket}/${uploadInfo.file_key}`,
      });

      clearSelectedUploadFile();

      showStatus(
        "Upload accepted. You can upload another file now, or check processing status after 30–60 seconds.",
        "success"
      );
    } catch (error) {
      showStatus(error.message, "error");
    } finally {
      setIsUploading(false);
    }
  }

  async function searchByThumbnail() {
    try {
      showStatus("Looking up original file from thumbnail URL...", "info");

      const data = await apiRequest("/media/search-by-thumbnail", {
        method: "POST",
        body: JSON.stringify({
          thumbnail_url: thumbnailUrl.trim(),
        }),
      });

      setThumbnailResult(data);
      showStatus("Thumbnail lookup completed.", "success");
    } catch (error) {
      showStatus(error.message, "error");
    }
  }

  async function searchByQueryUpload(event) {
    event.preventDefault();

    if (!selectedQueryFile) {
      showStatus("Please choose a query image or video file first.", "error");
      return;
    }

    try {
      showStatus("Requesting temporary query upload URL...", "info");

      const queryUploadInfo = await apiRequest("/query/generate-upload-url", {
        method: "POST",
        body: JSON.stringify({
          filename: selectedQueryFile.name,
          content_type: selectedQueryFile.type,
        }),
      });

      showStatus("Uploading temporary query file to S3...", "info");

      const s3Response = await fetch(queryUploadInfo.upload_url, {
        method: "PUT",
        headers: {
          "Content-Type": selectedQueryFile.type,
        },
        body: selectedQueryFile,
      });

      if (!s3Response.ok) {
        throw new Error(
          `Temporary query upload failed with HTTP ${s3Response.status}`
        );
      }

      showStatus("Detecting tags and searching matching media...", "info");

      const data = await apiRequest("/media/search-by-query-upload", {
        method: "POST",
        body: JSON.stringify({
          query_bucket: queryUploadInfo.query_bucket,
          query_key: queryUploadInfo.query_key,
          content_type: selectedQueryFile.type,
          file_type: queryUploadInfo.file_type,
        }),
      });

      const enrichedData = await enrichResultUrls(data);

      setQueryUploadResult(enrichedData);
      setSelectedQueryFile(null);
      showStatus(
        "Reverse search completed. Temporary query file was deleted.",
        "success"
      );
    } catch (error) {
      showStatus(error.message, "error");
    }
  }

  async function updateBulkTags() {
    try {
      showStatus("Applying bulk tag update...", "info");

      const urls = bulkUrls
        .split("\n")
        .map((url) => url.trim())
        .filter(Boolean);

      const tags = JSON.parse(bulkTagsJson);

      const data = await apiRequest("/media/bulk-tags", {
        method: "POST",
        body: JSON.stringify({
          urls,
          tags,
          operation: Number(bulkOperation),
        }),
      });

      setBulkTagResult(data);
      showStatus("Bulk tag operation completed.", "success");
    } catch (error) {
      showStatus(error.message, "error");
    }
  }

  async function deleteFiles() {
    try {
      showStatus("Deleting selected files...", "info");

      const urls = deleteUrls
        .split("\n")
        .map((url) => url.trim())
        .filter(Boolean);

      const data = await apiRequest("/media/files", {
        method: "DELETE",
        body: JSON.stringify({ urls }),
      });

      setDeleteResult(data);
      showStatus("Delete operation completed.", "success");
    } catch (error) {
      showStatus(error.message, "error");
    }
  }

  function renderLockedScreen() {
    return (
      <section className="locked-screen">
        <div className="locked-card">
          <div className="locked-brand-mark">AE</div>
          <p className="eyebrow">Secure multi-cloud platform</p>
          <h1>Aussie EcoLens</h1>
          <p>
            Sign in with AWS Cognito to upload, classify, search, manage, and
            delete wildlife media across AWS and GCP.
          </p>
          <button onClick={login} disabled={loadingAuth}>
            {loadingAuth ? "Opening Cognito..." : "Sign in / Sign up"}
          </button>
          {authMessage && <small>{authMessage}</small>}
        </div>
      </section>
    );
  }

  function renderDashboard() {
    return (
      <>
        <section className="hero-shell">
          <div className="hero-copy">
            <p className="eyebrow">FIT5225 Assignment 2</p>
            <h1>Aussie EcoLens Control Hub</h1>
            <p>
              Protected multi-cloud media operations for wildlife uploads,
              tagging, search, reverse lookup, manual tag management, and
              deletion across AWS and GCP.
            </p>
          </div>

          <div className="hero-actions">
            <div className="hero-badge">
              <span>Session</span>
              <strong>{isAuthenticated ? "Authenticated" : "Locked"}</strong>
            </div>
            <button onClick={loadTagSummary}>Refresh tag summary</button>
          </div>
        </section>

        <section className="metrics-strip">
          <MiniMetric
            label="Cloud stack"
            value={dashboardStats.providers}
            helper="Serverless + ML"
          />
          <MiniMetric
            label="Access"
            value="Cognito JWT"
            helper={dashboardStats.auth}
          />
          <MiniMetric
            label="Files scanned"
            value={dashboardStats.totalFiles}
            helper="DynamoDB records"
          />
          <MiniMetric
            label="Known tags"
            value={dashboardStats.tagCount}
            helper="Detected + manual"
          />
        </section>

        <section className="workspace-card">
          <div className="section-heading">
            <p className="eyebrow">Operations overview</p>
            <h2>Media pipeline control panel</h2>
            <p>
              Monitor the main cloud workflow from authenticated upload through
              classification, searchable metadata, tag management, and controlled
              deletion.
            </p>
          </div>

          <div className="capability-grid">
            <div>Authenticated access</div>
            <div>S3 media intake</div>
            <div>Cloud ML inference</div>
            <div>Metadata search</div>
            <div>Tag maintenance</div>
            <div>Storage cleanup</div>
          </div>

          <PrettyJson data={tagSummary} />
        </section>
      </>
    );
  }

  function renderUpload() {
    return (
      <section className="workspace-card workspace-split">
        <div>
          <div className="section-heading">
            <p className="eyebrow">Module</p>
            <h2>Upload media</h2>
            <p>
              Upload an image or video to S3 using a protected pre-signed URL.
              The backend pipeline handles deduplication, thumbnail generation,
              ML tagging, and DynamoDB updates.
            </p>
          </div>

          <form onSubmit={uploadMedia}>
            <label className="upload-panel">
              <input
                ref={uploadInputRef}
                type="file"
                accept="image/*,video/*"
                onChange={(event) =>
                  setSelectedUploadFile(event.target.files?.[0] || null)
                }
              />
              <div className="upload-panel-mark">AE</div>
              <strong>Choose media file</strong>
              <small>Images and videos are supported.</small>
            </label>

            {selectedUploadFile && (
              <div className="selected-file-card">
                <strong>{selectedUploadFile.name}</strong>
                <span>
                  {(selectedUploadFile.size / (1024 * 1024)).toFixed(2)} MB ·{" "}
                  {selectedUploadFile.type}
                </span>
                <small>{isUploading ? "Upload in progress" : "Ready for upload"}</small>

                <button
                  type="button"
                  className="ghost-button inline-clear-button"
                  onClick={clearSelectedUploadFile}
                  disabled={isUploading}
                >
                  Clear selected file
                </button>
              </div>
            )}

            <button
              className="primary-wide-button"
              type="submit"
              disabled={isUploading}
            >
              {isUploading ? "Uploading... please wait" : "Upload media"}
            </button>
          </form>

          <PrettyJson data={uploadResult} />

          {uploadResult && (
            <div className="upload-actions">
              <button type="button" onClick={checkLatestUploadStatus}>
                Check processing status
              </button>

              <button type="button" className="ghost-button" onClick={loadTagSummary}>
                Refresh tag summary
              </button>

              <button
                type="button"
                className="ghost-button"
                onClick={() => {
                  setUploadResult(null);
                  setUploadStatusResult(null);
                  setLatestUploadFileId("");
                  clearSelectedUploadFile();
                  showStatus(
                    "Upload panel cleared. Choose another file to upload.",
                    "info"
                  );
                }}
              >
                Clear upload panel
              </button>
            </div>
          )}

          <PrettyJson data={uploadStatusResult} />
        </div>

        <aside className="insight-card">
          <p className="eyebrow">Workflow</p>
          <h3>Browser → API Gateway → S3</h3>
          <p>
            After upload, you can select another file immediately. Backend
            processing runs asynchronously, so use Check processing status after
            30–60 seconds to confirm when tagging is complete.
          </p>
        </aside>
      </section>
    );
  }

  function renderSearch() {
    return (
      <section className="workspace-card">
        <div className="section-heading">
          <p className="eyebrow">Module</p>
          <h2>Search library</h2>
          <p>
            Search stored wildlife records by species tag or by JSON tag counts.
            Thumbnail previews are shown when browser-viewable URLs are available.
          </p>
        </div>

        <div className="mode-switch">
          <button
            className={searchMode === "species" ? "switch-active" : ""}
            onClick={() => setSearchMode("species")}
          >
            Species
          </button>
          <button
            className={searchMode === "tags" ? "switch-active" : ""}
            onClick={() => setSearchMode("tags")}
          >
            Tag counts
          </button>
        </div>

        {searchMode === "species" ? (
          <div className="action-form">
            <label>Species tag</label>
            <input
              value={speciesName}
              onChange={(event) => setSpeciesName(event.target.value)}
              placeholder="Canis_familiaris"
            />
            <button onClick={searchBySpecies}>Run species search</button>
          </div>
        ) : (
          <div className="action-form">
            <label>Tag-count JSON</label>
            <textarea
              rows={6}
              value={searchTagsJson}
              onChange={(event) => setSearchTagsJson(event.target.value)}
            />
            <button onClick={searchByTags}>Run tag-count search</button>
          </div>
        )}

        <div className="hint-row">
          <span>Examples</span>
          <code>Canis_familiaris</code>
          <code>Alectura_lathami</code>
          <code>{'{"Canis_familiaris": 1}'}</code>
        </div>

        <ResultCards data={searchResult} />
        <PrettyJson data={searchResult} />
      </section>
    );
  }

  function renderThumbnailLookup() {
    return (
      <section className="workspace-card">
        <div className="section-heading">
          <p className="eyebrow">Module</p>
          <h2>Thumbnail lookup</h2>
          <p>
            Paste a stored thumbnail URL and retrieve the corresponding original
            image URL.
          </p>
        </div>

        <div className="action-form">
          <label>Thumbnail URL</label>
          <input
            value={thumbnailUrl}
            onChange={(event) => setThumbnailUrl(event.target.value)}
            placeholder="s3://your-thumbnails-bucket/thumbnails/..."
          />
          <button onClick={searchByThumbnail}>Find original file</button>
        </div>

        <PrettyJson data={thumbnailResult} />
      </section>
    );
  }

  function renderReverseSearch() {
    return (
      <section className="workspace-card workspace-split">
        <div>
          <div className="section-heading">
            <p className="eyebrow">Module</p>
            <h2>Reverse search</h2>
            <p>
              Upload a temporary query file. The backend detects its tags,
              searches matching stored files, and deletes the temporary query
              object after processing.
            </p>
          </div>

          <form onSubmit={searchByQueryUpload}>
            <label className="upload-panel">
              <input
                type="file"
                accept="image/*,video/*"
                onChange={(event) =>
                  setSelectedQueryFile(event.target.files?.[0] || null)
                }
              />
              <div className="upload-panel-mark">Q</div>
              <strong>Choose query file</strong>
              <small>Temporary file only — not permanently stored.</small>
            </label>

            {selectedQueryFile && (
              <div className="selected-file-card">
                <strong>{selectedQueryFile.name}</strong>
                <span>
                  {(selectedQueryFile.size / (1024 * 1024)).toFixed(2)} MB ·{" "}
                  {selectedQueryFile.type}
                </span>
                <small>Ready for reverse search</small>
              </div>
            )}

            <button className="primary-wide-button" type="submit">
              Upload query file and search
            </button>
          </form>

          <ResultCards data={queryUploadResult} />
          <PrettyJson data={queryUploadResult} />
        </div>

        <aside className="insight-card">
          <p className="eyebrow">Expected evidence</p>
          <h3>Temporary file cleanup</h3>
          <p>
            Successful output should show <code>temporary_file_deleted: true</code>.
          </p>
        </aside>
      </section>
    );
  }

  function renderTags() {
    return (
      <section className="workspace-card">
        <div className="section-heading">
          <p className="eyebrow">Module</p>
          <h2>Manage tags</h2>
          <p>Add or remove manual tags for one or more stored media URLs.</p>
        </div>

        <div className="stack-form">
          <label>Media URLs, one per line</label>
          <textarea
            rows={5}
            value={bulkUrls}
            onChange={(event) => setBulkUrls(event.target.value)}
            placeholder="s3://your-originals-bucket/uploads/..."
          />

          <label>Tags JSON</label>
          <textarea
            rows={4}
            value={bulkTagsJson}
            onChange={(event) => setBulkTagsJson(event.target.value)}
          />

          <label>Operation</label>
          <select
            value={bulkOperation}
            onChange={(event) => setBulkOperation(event.target.value)}
          >
            <option value="1">1 - Add/update tags</option>
            <option value="0">0 - Remove tags</option>
          </select>

          <button onClick={updateBulkTags}>Apply tag operation</button>
        </div>

        <PrettyJson data={bulkTagResult} />
      </section>
    );
  }

  function renderDelete() {
    return (
      <section className="workspace-card danger-zone">
        <div className="section-heading">
          <p className="eyebrow">Module</p>
          <h2>Delete files</h2>
          <p>
            Delete original media, thumbnails when present, and DynamoDB records.
            Use only for test/demo files.
          </p>
        </div>

        <div className="stack-form">
          <label>Media URLs, one per line</label>
          <textarea
            rows={6}
            value={deleteUrls}
            onChange={(event) => setDeleteUrls(event.target.value)}
            placeholder="s3://your-originals-bucket/uploads/..."
          />

          <button className="danger-button" onClick={deleteFiles}>
            Delete selected files
          </button>
        </div>

        <PrettyJson data={deleteResult} />
      </section>
    );
  }

  function renderEvidence() {
    return (
      <section className="workspace-card">
        <div className="section-heading">
          <p className="eyebrow">Checklist</p>
          <h2>Demo evidence</h2>
          <p>
            Use this area as a reminder for final screenshots and demo coverage.
          </p>
        </div>

        <div className="evidence-board">
          <div>
            <strong>SNS email notification</strong>
            <span>Show tagging notification email.</span>
          </div>
          <div>
            <strong>Protected API</strong>
            <span>Show unauthenticated request blocked.</span>
          </div>
          <div>
            <strong>Protected GCP predict</strong>
            <span>Show direct unauthorized access failure.</span>
          </div>
          <div>
            <strong>Video evidence</strong>
            <span>Show frame-based tag aggregation.</span>
          </div>
        </div>
      </section>
    );
  }

  function renderActiveModule() {
    if (!isAuthenticated) return renderLockedScreen();

    switch (activeModule) {
      case "dashboard":
        return renderDashboard();
      case "upload":
        return renderUpload();
      case "search":
        return renderSearch();
      case "thumbnail":
        return renderThumbnailLookup();
      case "reverse":
        return renderReverseSearch();
      case "tags":
        return renderTags();
      case "delete":
        return renderDelete();
      case "evidence":
        return renderEvidence();
      default:
        return renderDashboard();
    }
  }

  const activeLabel =
    NAV_ITEMS.find((item) => item.id === activeModule)?.label || "Overview";

  return (
    <main className={`hub-layout ${sidebarCollapsed ? "sidebar-collapsed" : ""}`}>
      {isAuthenticated && (
        <aside className="hub-sidebar">
          <div className="sidebar-top">
            <div className="brand-lockup">
              <div className="brand-badge">AE</div>
              {!sidebarCollapsed && (
                <div className="brand-copy">
                  <strong>Aussie EcoLens</strong>
                  <span>Wildlife media control hub</span>
                </div>
              )}
            </div>

            <button
              className="collapse-toggle"
              onClick={() => setSidebarCollapsed((prev) => !prev)}
              aria-label="Toggle sidebar"
              title="Toggle sidebar"
            >
              {sidebarCollapsed ? "»" : "«"}
            </button>
          </div>

          <nav className="sidebar-nav">
            {NAV_ITEMS.map((item) => (
              <button
                key={item.id}
                className={activeModule === item.id ? "nav-item active" : "nav-item"}
                onClick={() => setActiveModule(item.id)}
                aria-label={item.label}
                title={item.label}
              >
                <span className="nav-icon">{item.icon}</span>
                {!sidebarCollapsed && <span className="nav-text">{item.label}</span>}
              </button>
            ))}
          </nav>

          <div className="sidebar-footer">
            <div className="account-panel">
              <div className="account-dot" />
              {!sidebarCollapsed && (
                <div className="account-copy">
                  <strong>Authenticated</strong>
                  <small>{maskedToken}</small>
                </div>
              )}
            </div>

            <button className="logout-button" onClick={logout}>
              {sidebarCollapsed ? "⏻" : "Sign out"}
            </button>
          </div>
        </aside>
      )}

      <section className="hub-main">
        {isAuthenticated && (
          <header className="top-command-bar">
            <div>
              <p className="page-kicker">Aussie EcoLens</p>
              <h1>{activeLabel}</h1>
            </div>

            <div className="top-command-actions">
              <div className="session-chip">
                <span>Session</span>
                <strong>{isAuthenticated ? "Protected" : "Locked"}</strong>
              </div>
            </div>
          </header>
        )}

        {statusMessage && (
          <div className={`status-banner ${statusType}`}>{statusMessage}</div>
        )}

        {renderActiveModule()}
      </section>
    </main>
  );
}

export default App;
