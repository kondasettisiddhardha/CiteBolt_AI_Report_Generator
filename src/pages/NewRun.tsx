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
      saveDraft({
        topic: draft.topic,
        context: draft.context,
        reportType: draft.reportType,
        length: draft.length,
        template_outline: draft.template_outline,
        front_matter: draft.front_matter,
      });
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
          length: draft.length ?? "standard",
          targetWords: draft.targetWords ?? 4000,
          template_outline: draft.template_outline,
          outline: draft.template_outline,
          front_matter: draft.front_matter,
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
    <div className="w-full py-2">
      <RunComposer starting={starting} onStart={start} />
    </div>
  );
}
