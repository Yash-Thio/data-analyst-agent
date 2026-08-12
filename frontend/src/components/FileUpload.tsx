"use client";

import { useRef, useState } from "react";
import type { DatasetProfile } from "@/lib/api";
import { uploadDataset } from "@/lib/api";

type Props = {
  onUploaded: (datasetId: string, profile: DatasetProfile, filename: string) => void;
};

export function FileUpload({ onUploaded }: Props) {
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

  return (
    <div
      className={`rounded-xl border-2 border-dashed p-8 text-center transition ${
        dragging ? "border-indigo-500 bg-indigo-50 dark:bg-indigo-950/30" : "border-zinc-300 dark:border-zinc-700"
      }`}
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
      <p className="text-lg font-medium text-zinc-800 dark:text-zinc-100">Upload a CSV dataset</p>
      <p className="mt-1 text-sm text-zinc-500">Drag and drop, or click to browse</p>
      <button
        type="button"
        disabled={loading}
        onClick={() => inputRef.current?.click()}
        className="mt-4 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
      >
        {loading ? "Uploading…" : "Choose file"}
      </button>
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
      {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
    </div>
  );
}
