import { useState, useEffect } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ArrowRight, Loader2, MailCheck } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import ThemeToggle, { type ThemeMode } from "@/components/ThemeToggle";
import { useAuth } from "@/hooks/useAuth";

export default function Login() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const { refresh, user, loading } = useAuth();
  const [step, setStep] = useState<"email" | "code">("email");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cooldown, setCooldown] = useState(0);

  const redirectTo = params.get("next") || "/workspace";

  useEffect(() => {
    if (!loading && user) navigate(redirectTo, { replace: true });
  }, [user, loading, redirectTo, navigate]);

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = window.setTimeout(() => setCooldown((value) => value - 1), 1000);
    return () => window.clearTimeout(timer);
  }, [cooldown]);

  async function sendCode(event?: React.FormEvent) {
    event?.preventDefault();
    if (!email.trim()) return;
    setBusy(true);
    try {
      const data = await api<{ detail: string; delivered: boolean }>("/api/auth/request-otp", {
        method: "POST",
        body: JSON.stringify({ email: email.trim().toLowerCase() }),
      });
      setStep("code");
      setCooldown(30);
      toast.message(data.detail);
      if (!data.delivered) toast.message("Check the backend console for your code.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not send the code.");
    } finally {
      setBusy(false);
    }
  }

  async function verify(event?: React.FormEvent) {
    event?.preventDefault();
    if (code.length !== 6) return;
    setBusy(true);
    try {
      await api("/api/auth/verify-otp", {
        method: "POST",
        body: JSON.stringify({ email: email.trim().toLowerCase(), code }),
      });
      await refresh();
      toast.success("Signed in");
      navigate(redirectTo, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not verify that code.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen flex-col bg-bg px-5 py-6">
      <div className="flex items-center justify-between">
        <Link to="/" className="text-sm font-semibold tracking-[0.18em] text-fg">
          <span className="inline-flex h-7 w-7 items-center justify-center rounded-lg bg-gradient-to-br from-teal-300 to-emerald-500 text-sm font-bold text-[#06110d]">
            D
          </span>
          <span className="text-sm tracking-[0.16em] text-fg">DOSSIER</span>
        </Link>
        <ThemeToggle mode={loading ? "system" : "light"} onChange={() => {}} className="!h-8 !w-8" aria-label="Switch theme" />
      </div>

      <div className="flex flex-1 items-center justify-center py-10">
        <div className="w-full max-w-[420px]">
          <div className="rounded-2xl border border-line bg-surface p-7 shadow-[var(--card-shadow)]">
            <span className="inline-flex h-10 w-10 items-center justify-center rounded-full bg-accent-soft text-accent">
              <MailCheck className="h-5 w-5" aria-hidden="true" />
            </span>
            <h1 className="mt-4 text-2xl font-bold tracking-tight text-fg">
              {step === "email" ? "Sign in to Dossier" : "Enter your code"}
            </h1>
            <p className="mt-2 text-sm text-muted">
              {step === "email"
                ? "We'll email you a 6-digit code. No password to remember."
                : `We sent a code to ${email}. It expires in 10 minutes.`}
            </p>

            {step === "email" ? (
              <form onSubmit={sendCode} className="mt-6 space-y-3">
                <label className="block text-xs font-medium text-muted" htmlFor="email">
                  Email address
                </label>
                <input
                  id="email"
                  type="email"
                  required
                  autoFocus
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  placeholder="you@example.com"
                  className="h-11 w-full rounded-lg border border-line bg-bg px-4 text-sm text-fg placeholder:text-muted focus:border-line-strong focus:outline-none focus:ring-2 focus:ring-ring"
                />
                {error && <p className="text-xs text-red-600">{error}</p>}
                <button
                  type="submit"
                  disabled={busy || !email.trim()}
                  className="inline-flex h-11 w-full items-center justify-center gap-2 rounded-lg bg-primary text-sm font-medium text-primary-fg transition disabled:opacity-50"
                >
                  {busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <ArrowRight className="h-4 w-4" aria-hidden="true" />}
                  Send code
                </button>
              </form>
            ) : (
              <form onSubmit={verify} className="mt-6 space-y-3">
                <label className="block text-xs font-medium text-muted" htmlFor="code">
                  6-digit code
                </label>
                <input
                  id="code"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  autoFocus
                  value={code}
                  onChange={(event) => setCode(event.target.value.replace(/\D/g, "").slice(0, 6))}
                  placeholder="123456"
                  className="h-12 w-full rounded-lg border border-line bg-bg px-4 text-center text-lg tracking-[0.4em] text-fg placeholder:text-muted focus:border-line-strong focus:outline-none focus:ring-2 focus:ring-ring"
                />
                {error && <p className="text-xs text-red-600">{error}</p>}
                <button
                  type="submit"
                  disabled={busy || code.length !== 6}
                  className="inline-flex h-11 w-full items-center justify-center gap-2 rounded-lg bg-primary text-sm font-medium text-primary-fg transition disabled:opacity-50"
                >
                  {busy && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />}
                  Verify and sign in
                </button>

                <div className="flex items-center justify-between pt-1 text-xs text-muted">
                  <button
                    type="button"
                    onClick={() => void sendCode()}
                    disabled={cooldown > 0 || busy}
                    className="underline-offset-2 hover:text-fg disabled:opacity-50"
                  >
                    {cooldown > 0 ? `Resend code in ${cooldown}s` : "Resend code"}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setStep("email");
                      setCode("");
                      setError(null);
                    }}
                    className="hover:text-fg"
                  >
                    Change email
                  </button>
                </div>
              </form>
            )}
          </div>

          <p className="mt-4 text-center text-xs text-muted">
            By continuing you agree to our <Link to="/terms" className="underline">terms</Link> and{" "}
            <Link to="/privacy" className="underline">privacy policy</Link>
            .
          </p>
        </div>
      </div>
    </div>
  );
}
