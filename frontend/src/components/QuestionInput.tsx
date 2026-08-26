"use client";

import { FormEvent, useState } from "react";

type Props = {
  disabled?: boolean;
  onSubmit: (question: string) => void;
};

export function QuestionInput({ disabled, onSubmit }: Props) {
  const [question, setQuestion] = useState("");

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!question.trim() || disabled) return;
    onSubmit(question.trim());
  }

  return (
    <form onSubmit={handleSubmit} className="flex gap-2">
      <input
        type="text"
        value={question}
        onChange={(e) => setQuestion(e.target.value)}
        disabled={disabled}
        placeholder="Ask a question about your data…"
        className="min-w-0 flex-1 rounded-full border border-[var(--separator)] bg-[var(--surface-solid)] px-4 py-3 text-sm outline-none focus:border-[var(--accent)] disabled:opacity-50"
      />
      <button
        type="submit"
        disabled={disabled || !question.trim()}
        className="btn btn-primary shrink-0"
      >
        Analyze
      </button>
    </form>
  );
}
