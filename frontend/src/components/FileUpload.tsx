"use client";

import { useRef, useState } from "react";
import type { DatasetProfile } from "@/lib/api";
import { uploadDataset } from "@/lib/api";

type Props = {
  onUploaded: (datasetId: string, profile: DatasetProfile, filename: string) => void;
  compact?: boolean;
};

export function FileUpload({ onUploaded, compact = false }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleFile(file: File) {
    setError(null);
    setLoading(true);
    try {
      const result = await uploadDataset(file);
      onUploaded(result.dataset_id, result.profile, file.name);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setLoading(false);
    }
  }

  const fileInput = (
    <input
      ref={inputRef}
      type="file"
      accept=".csv"
      className="hidden"
      onChange={(e) => {
        const file = e.target.files?.[0];
        if (file) void handleFile(file);
      }}
    />
  );

  if (compact) {
    return (
      <div className="text-right">
        <button
          type="button"
          disabled={loading}
          className="btn btn-quiet text-xs"
          onClick={() => inputRef.current?.click()}
        >
          {loading ? "Uploading…" : "Replace CSV"}
        </button>
        {fileInput}
        {error && <p className="mt-1 text-xs text-[var(--danger)]">{error}</p>}
      </div>
    );
  }

  return (
    <div
      className={`drop-well flex w-full max-w-[560px] cursor-pointer flex-col items-center px-8 py-14 text-center ${
        dragging ? "is-dragging" : ""
      }`}
      onClick={() => {
        if (!loading) inputRef.current?.click();
      }}
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        const file = e.dataTransfer.files?.[0];
        if (file) void handleFile(file);
      }}
    >
      <p className="text-lg font-medium tracking-tight">Upload a CSV dataset</p>
      <p className="mt-1 text-sm text-[var(--label-secondary)]">Drag and drop, or click to browse</p>
      <button
        type="button"
        disabled={loading}
        className="btn btn-primary mt-6"
        onClick={(e) => {
          e.stopPropagation();
          inputRef.current?.click();
        }}
      >
        {loading ? "Uploading…" : "Choose file"}
      </button>
      {fileInput}
      {error && <p className="mt-4 text-sm text-[var(--danger)]">{error}</p>}
    </div>
  );
}
