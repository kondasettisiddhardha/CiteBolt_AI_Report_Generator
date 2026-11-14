import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import RunComposer, { type RunDraft } from "@/components/RunComposer";
import { api } from "@/lib/api";
import { clearDraft, loginUrl, saveDraft } from "@/lib/session";
import { useAuth } from "@/hooks/useAuth";

export default function NewRun() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [starting, setStarting] = useState(false);

  async function start(draft: RunDraft) {
    if (!user) {
      saveDraft({ topic: draft.topic, context: draft.context, reportType: draft.reportType });
      navigate(loginUrl("/runs/new"));
      return;
    }

    setStarting(true);
    try {
      const data = await api<{ run_id: string }>("/api/research", {
        method: "POST",
        body: JSON.stringify({
          topic: draft.topic,
          context: draft.context,
          reportType: draft.reportType,
        }),
      });
      clearDraft();
      navigate(`/runs/${data.run_id}`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not start that run.");
    } finally {
      setStarting(false);
    }
  }

  return (
    <div className="text-left">
      <header className="mb-6">
        <p className="text-[13px] font-semibold uppercase tracking-[0.2em] text-accent">
          New research run
        </p>
        <h1 className="mt-2 text-[28px] font-bold tracking-tight text-fg sm:text-[34px]">
          What should we research?
        </h1>
        <p className="mt-2 max-w-[640px] text-[16px] sm:text-[17px] leading-relaxed text-muted">
          Give the planner a topic, add any background material, and pick the shape the report
          should take.
        </p>
        {!user && (
          <p className="mt-3 inline-flex rounded-lg border border-line bg-surface px-3 py-2 text-xs text-muted">
            You can draft the brief now. Starting the run requires an account — your topic is kept
            when you sign in.
          </p>
        )}
      </header>

      <RunComposer starting={starting} onStart={start} />
    </div>
  );
}
