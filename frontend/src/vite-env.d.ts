/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Backend base URL when it is deployed separately (default: same-origin "/api"). */
  readonly VITE_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
