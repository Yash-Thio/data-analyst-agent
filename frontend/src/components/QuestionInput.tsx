"use client";

import { FormEvent, useState } from "react";

type Props = {
  disabled?: boolean;
  onSubmit: (question: string) => void;
};

export function QuestionInput({ disabled, onSubmit }: Props) {
  const [question, setQuestion] = useState("Why did revenue drop in Q3?");

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
        className="flex-1 rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm outline-none focus:border-indigo-500 dark:border-zinc-700 dark:bg-zinc-900"
      />
      <button
        type="submit"
        disabled={disabled || !question.trim()}
        className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
      >
        Analyze
      </button>
    </form>
  );
}
