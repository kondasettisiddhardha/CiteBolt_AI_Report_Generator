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
    <div className="text-left">
      <header className="mb-6">
        <p className="text-[13px] font-semibold uppercase tracking-[0.2em] text-accent">
          Support & Feedback
        </p>
        <h1 className="mt-2 text-[28px] font-bold tracking-tight text-fg sm:text-[34px]">
          Contact
        </h1>
        <p className="mt-2 max-w-[640px] text-[16px] sm:text-[17px] leading-relaxed text-muted">
          Questions, bugs or feature ideas — send a note and a human will read it.
        </p>
        {SUPPORT_EMAIL && (
          <p className="mt-2 text-xs text-muted">
            Direct email: <a href={`mailto:${SUPPORT_EMAIL}`} className="text-accent underline">{SUPPORT_EMAIL}</a>
          </p>
        )}
      </header>

      <form onSubmit={submit} className="mt-6 max-w-[720px] rounded-2xl border border-line bg-surface p-6">
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label htmlFor="name" className="block text-xs font-medium text-muted">
              Name
            </label>
            <input
              id="name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Your name"
              className="mt-1 h-10 w-full rounded-lg border border-line bg-bg px-3 text-sm text-fg placeholder:text-muted focus:border-accent focus:outline-none focus:ring-2 focus:ring-ring dark:border-white/20"
            />
            {errors.name && <p className="mt-1 text-xs text-red-500">{errors.name}</p>}
          </div>

          <div>
            <label htmlFor="email" className="block text-xs font-medium text-muted">
              Email
            </label>
            <input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@company.com"
              className="mt-1 h-10 w-full rounded-lg border border-line bg-bg px-3 text-sm text-fg placeholder:text-muted focus:border-accent focus:outline-none focus:ring-2 focus:ring-ring dark:border-white/20"
            />
            {errors.email && <p className="mt-1 text-xs text-red-500">{errors.email}</p>}
          </div>
        </div>

        <div className="mt-4">
          <label htmlFor="subject" className="block text-xs font-medium text-muted">
            Subject
          </label>
          <input
            id="subject"
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            placeholder="What is this about?"
            className="mt-1 h-10 w-full rounded-lg border border-line bg-bg px-3 text-sm text-fg placeholder:text-muted focus:border-accent focus:outline-none focus:ring-2 focus:ring-ring dark:border-white/20"
          />
          {errors.subject && <p className="mt-1 text-xs text-red-500">{errors.subject}</p>}
        </div>

        <div className="mt-4">
          <label htmlFor="message" className="block text-xs font-medium text-muted">
            Message
          </label>
          <textarea
            id="message"
            rows={5}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            placeholder="Tell us what happened, or what you'd like to see..."
            className="mt-1 w-full rounded-lg border border-line bg-bg p-3 text-sm text-fg placeholder:text-muted focus:border-accent focus:outline-none focus:ring-2 focus:ring-ring dark:border-white/20"
          />
          {errors.message && <p className="mt-1 text-xs text-red-500">{errors.message}</p>}
        </div>

        <div className="mt-6 flex justify-end">
          <button
            type="submit"
            disabled={busy}
            className="inline-flex h-[42px] items-center gap-2 rounded-lg bg-primary px-5 text-sm font-medium text-primary-fg shadow-sm transition hover:-translate-y-px disabled:opacity-50"
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
            <span>Send message</span>
          </button>
        </div>
      </form>
    </div>
  );
}
