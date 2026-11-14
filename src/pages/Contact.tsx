import { useState } from "react";
import { Loader2, Send } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useAuth } from "@/hooks/useAuth";

const SUPPORT_EMAIL = (import.meta.env.VITE_SUPPORT_EMAIL as string | undefined)?.trim();

export default function Contact() {
  const { user } = useAuth();
  const [name, setName] = useState("");
  const [email, setEmail] = useState(user?.email ?? "");
  const [subject, setSubject] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const next: Record<string, string> = {};
    if (!name.trim()) next.name = "Tell us your name.";
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) next.email = "Enter a valid email.";
    if (!subject.trim()) next.subject = "Add a subject.";
    if (message.trim().length < 10) next.message = "Add a little more detail (10+ characters).";
    setErrors(next);
    if (Object.keys(next).length > 0) return;

    setBusy(true);
    try {
      await api("/api/contact", {
        method: "POST",
        body: JSON.stringify({ name, email, subject, message }),
      });
      toast.success("Message sent. We'll get back to you soon.");
      setSubject("");
      setMessage("");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not send your message.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="px-5 py-8 sm:px-10">
      <div className="mx-auto max-w-[720px]">
        <h1 className="text-2xl font-bold tracking-tight text-fg sm:text-[32px]">Contact</h1>
        <p className="mt-2 text-sm text-muted">
          Questions, bugs or feature ideas — send a note and a human will read it.
        </p>

        <form onSubmit={submit} className="mt-6 rounded-2xl border border-line bg-surface p-6">
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="name" className="block text-xs font-medium text-muted">
                Name
              </label>
              <input
                id="name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                className="mt-1 h-10 w-full rounded-lg border border-line bg-bg px-3 text-sm text-fg focus:border-line-strong focus:outline-none focus:ring-2 focus:ring-ring"
              />
              {errors.name && <p className="mt-1 text-xs text-red-600 dark:text-red-400">{errors.name}</p>}
            </div>
            <div>
              <label htmlFor="email" className="block text-xs font-medium text-muted">
                Email
              </label>
              <input
                id="email"
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                className="mt-1 h-10 w-full rounded-lg border border-line bg-bg px-3 text-sm text-fg focus:border-line-strong focus:outline-none focus:ring-2 focus:ring-ring"
              />
              {errors.email && <p className="mt-1 text-xs text-red-600 dark:text-red-400">{errors.email}</p>}
            </div>
          </div>

          <div className="mt-4">
            <label htmlFor="subject" className="block text-xs font-medium text-muted">
              Subject
            </label>
            <input
              id="subject"
              value={subject}
              onChange={(event) => setSubject(event.target.value)}
              className="mt-1 h-10 w-full rounded-lg border border-line bg-bg px-3 text-sm text-fg focus:border-line-strong focus:outline-none focus:ring-2 focus:ring-ring"
            />
            {errors.subject && <p className="mt-1 text-xs text-red-600 dark:text-red-400">{errors.subject}</p>}
          </div>

          <div className="mt-4">
            <label htmlFor="message" className="block text-xs font-medium text-muted">
              Message
            </label>
            <textarea
              id="message"
              rows={6}
              value={message}
              onChange={(event) => setMessage(event.target.value)}
              className="mt-1 w-full resize-y rounded-lg border border-line bg-bg px-3 py-2 text-sm text-fg focus:border-line-strong focus:outline-none focus:ring-2 focus:ring-ring"
            />
            {errors.message && <p className="mt-1 text-xs text-red-600 dark:text-red-400">{errors.message}</p>}
          </div>

          <div className="mt-5 flex flex-wrap items-center justify-between gap-3">
            {SUPPORT_EMAIL ? (
              <p className="text-xs text-muted">
                Or email us directly at{" "}
                <a href={`mailto:${SUPPORT_EMAIL}`} className="text-accent underline">
                  {SUPPORT_EMAIL}
                </a>
              </p>
            ) : <div />}
            <button
              type="submit"
              disabled={busy}
              className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-fg disabled:opacity-60"
            >
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
              Send message
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
