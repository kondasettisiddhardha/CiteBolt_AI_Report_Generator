import { useState, useEffect, useRef } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Check, ShieldCheck, Lock, Mail, User, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import ThemeToggle from "@/components/ThemeToggle";
import Wordmark from "@/components/Wordmark";
import { useAuth } from "@/hooks/useAuth";
import { getStoredTheme, setStoredTheme, watchSystemTheme, type ThemePreference } from "@/lib/theme";

function truncateEmail(str: string, max = 26): string {
  if (!str || str.length <= max) return str;
  const atIdx = str.indexOf("@");
  if (atIdx === -1) return str.slice(0, max - 3) + "...";
  const user = str.slice(0, atIdx);
  const domain = str.slice(atIdx + 1);
  if (domain.length >= max - 6) {
    return `${user.slice(0, 3)}...@${domain.slice(0, 10)}...`;
  }
  const availUser = max - domain.length - 4;
  return `${user.slice(0, Math.max(3, availUser))}...@${domain}`;
}

export default function Login() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const { refresh, user, loading } = useAuth();
  const [theme, setTheme] = useState<ThemePreference>(getStoredTheme);

  const [step, setStep] = useState<"email" | "code">("email");
  const [isFading, setIsFading] = useState(false);

  const [email, setEmail] = useState("");
  const [digits, setDigits] = useState<string[]>(["", "", "", "", "", ""]);
  const digitRefs = useRef<(HTMLInputElement | null)[]>([]);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cooldown, setCooldown] = useState(0);
  const [shake, setShake] = useState(false);

  const redirectTo = params.get("next") || "/workspace";

  useEffect(() => {
    return watchSystemTheme(() => {
      if (getStoredTheme() === "system") {
        setTheme("system");
      }
    });
  }, []);

  const handleThemeChange = (next: ThemePreference) => {
    setTheme(next);
    setStoredTheme(next);
  };

  useEffect(() => {
    if (!loading && user) navigate(redirectTo, { replace: true });
  }, [user, loading, redirectTo, navigate]);

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = window.setTimeout(() => setCooldown((value) => value - 1), 1000);
    return () => window.clearTimeout(timer);
  }, [cooldown]);

  const transitionTo = (nextStep: "email" | "code") => {
    setIsFading(true);
    setTimeout(() => {
      setStep(nextStep);
      setIsFading(false);
    }, 160);
  };

  useEffect(() => {
    if (step === "code") {
      const timer = window.setTimeout(() => {
        digitRefs.current[0]?.focus();
      }, 180);
      return () => window.clearTimeout(timer);
    }
  }, [step]);

  async function sendCode(event?: React.FormEvent) {
    event?.preventDefault();
    const cleanEmail = email.trim().toLowerCase();
    if (!cleanEmail) return;
    setBusy(true);
    setError(null);
    try {
      const data = await api<{ detail: string; delivered: boolean }>("/api/auth/request-otp", {
        method: "POST",
        body: JSON.stringify({ email: cleanEmail }),
      });
      setCooldown(30);
      setDigits(["", "", "", "", "", ""]);
      toast.message(data.detail);
      if (!data.delivered) toast.message("Check the backend console for your code.");
      transitionTo("code");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not send the code.");
    } finally {
      setBusy(false);
    }
  }

  async function verifyCode(codeToVerify: string) {
    if (codeToVerify.length !== 6 || busy) return;
    setBusy(true);
    setError(null);
    try {
      await api("/api/auth/verify-otp", {
        method: "POST",
        body: JSON.stringify({ email: email.trim().toLowerCase(), code: codeToVerify }),
      });
      await refresh();
      toast.success("Signed in");
      navigate(redirectTo, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Invalid code.");
      setShake(true);
      setDigits(["", "", "", "", "", ""]);
      window.setTimeout(() => {
        digitRefs.current[0]?.focus();
      }, 50);
      window.setTimeout(() => {
        setShake(false);
      }, 450);
    } finally {
      setBusy(false);
    }
  }

  function handleDigitChange(index: number, value: string) {
    const cleaned = value.replace(/\D/g, "");
    if (!cleaned) {
      const next = [...digits];
      next[index] = "";
      setDigits(next);
      return;
    }
    const char = cleaned.slice(-1);
    const next = [...digits];
    next[index] = char;
    setDigits(next);
    setError(null);

    if (index < 5) {
      digitRefs.current[index + 1]?.focus();
    } else {
      const fullCode = next.join("");
      if (fullCode.length === 6 && next.every((d) => d.length === 1)) {
        void verifyCode(fullCode);
      }
    }
  }

  function handleKeyDown(index: number, e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Backspace") {
      if (!digits[index] && index > 0) {
        e.preventDefault();
        const next = [...digits];
        next[index - 1] = "";
        setDigits(next);
        digitRefs.current[index - 1]?.focus();
      }
    } else if (e.key === "ArrowLeft" && index > 0) {
      e.preventDefault();
      digitRefs.current[index - 1]?.focus();
    } else if (e.key === "ArrowRight" && index < 5) {
      e.preventDefault();
      digitRefs.current[index + 1]?.focus();
    }
  }

  function handlePaste(e: React.ClipboardEvent<HTMLInputElement>) {
    e.preventDefault();
    const pasted = e.clipboardData.getData("text").replace(/\D/g, "").slice(0, 6);
    if (!pasted) return;

    const next = [...digits];
    for (let i = 0; i < 6; i++) {
      next[i] = pasted[i] || "";
    }
    setDigits(next);
    setError(null);

    const focusTarget = Math.min(pasted.length, 5);
    digitRefs.current[focusTarget]?.focus();

    if (pasted.length === 6) {
      void verifyCode(pasted);
    }
  }

  function handleChangeEmail() {
    setError(null);
    setDigits(["", "", "", "", "", ""]);
    transitionTo("email");
  }

  return (
    <div className="relative flex min-h-screen flex-col bg-bg text-fg">
      {/* Radial teal glow backdrop matching reference */}
      <div
        className="pointer-events-none fixed inset-0 z-0 bg-[radial-gradient(ellipse_75%_45%_at_50%_-10%,rgba(20,184,166,0.18),transparent_70%)] dark:bg-[radial-gradient(ellipse_75%_45%_at_50%_-10%,rgba(20,184,166,0.14),transparent_70%)]"
        aria-hidden="true"
      />

      {/* Top bar */}
      <header className="relative z-10 mx-auto flex w-full max-w-6xl items-center justify-between px-6 py-6 sm:px-8">
        <Link to="/" className="flex items-center gap-2.5 transition opacity-90 hover:opacity-100">
          <img src="/logo.svg" className="h-7 w-7 shrink-0 rounded-lg" alt="Citebolt logo" />
          <Wordmark size="md" />
        </Link>
        <div className="flex items-center gap-3">
          <ThemeToggle mode={theme} onChange={handleThemeChange} className="!h-8 !w-8" />
          <Link
            to="/"
            className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-line bg-surface/60 px-3 text-xs font-medium text-muted transition hover:border-line-strong hover:text-fg"
          >
            <span>&larr;</span> Back to site
          </Link>
        </div>
      </header>

      {/* Main 2-column container */}
      <main className="relative z-10 mx-auto flex w-full max-w-6xl flex-1 items-center px-6 py-8 sm:px-8">
        <div className="grid w-full grid-cols-1 items-center gap-12 lg:grid-cols-12 lg:gap-16">
          {/* Left column: ACCESS GATEWAY (persists across both steps without re-rendering or flicker) */}
          <div className="order-2 flex flex-col justify-center lg:order-1 lg:col-span-7">
            <span className="text-xs font-semibold uppercase tracking-[0.2em] text-accent">
              ACCESS GATEWAY
            </span>
            <h1 className="mt-3 text-3xl font-bold tracking-tight text-fg sm:text-4xl lg:text-[42px] lg:leading-[1.15]">
              Sign in to the room where reports get written.
            </h1>
            <p className="mt-4 max-w-lg text-sm leading-relaxed text-muted sm:text-base">
              One account keeps your runs, evidence, and drafts together. No password to remember, a six-digit code does the work.
            </p>

            <div className="mt-8 space-y-4">
              <div className="flex items-start gap-3.5">
                <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-line bg-surface text-accent">
                  <Check className="h-4 w-4" aria-hidden="true" />
                </div>
                <p className="text-sm leading-relaxed text-muted">
                  <strong className="font-semibold text-fg">Every citation stays checkable.</strong> Sources are fetched live and listed with each report.
                </p>
              </div>

              <div className="flex items-start gap-3.5">
                <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-line bg-surface text-accent">
                  <ShieldCheck className="h-4 w-4" aria-hidden="true" />
                </div>
                <p className="text-sm leading-relaxed text-muted">
                  <strong className="font-semibold text-fg">Passwordless by design.</strong> Codes expire in 10 minutes and are delivered to your inbox only.
                </p>
              </div>

              <div className="flex items-start gap-3.5">
                <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-line bg-surface text-accent">
                  <Lock className="h-4 w-4" aria-hidden="true" />
                </div>
                <p className="text-sm leading-relaxed text-muted">
                  <strong className="font-semibold text-fg">Your workspace is private.</strong> Runs are scoped to your account, not shared across visitors.
                </p>
              </div>
            </div>
          </div>

          {/* Right column: Card slot */}
          <div className="order-1 flex w-full flex-col items-center lg:order-2 lg:col-span-5 lg:items-end">
            <div className="w-full max-w-[420px]">
              <div className="w-full rounded-2xl border border-line bg-surface p-6 shadow-lg shadow-black/5 dark:shadow-black/20 sm:p-7">
                <div
                  className={`transition-all duration-200 ease-out ${
                    isFading ? "translate-y-1 opacity-0" : "translate-y-0 opacity-100"
                  }`}
                >
                  {step === "email" ? (
                    <div>
                      {/* Step 1 Header */}
                      <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-accent">
                        <Mail className="h-4 w-4" aria-hidden="true" />
                        <span>STEP 1 OF 2</span>
                      </div>
                      <h2 className="mt-3 text-2xl font-bold tracking-tight text-fg">
                        Enter your email
                      </h2>
                      <p className="mt-1.5 text-xs text-muted sm:text-sm">
                        We'll send a one-time code. New here? The same step creates your account.
                      </p>

                      {/* Step 1 Form */}
                      <form onSubmit={sendCode} className="mt-6 space-y-4">
                        <div>
                          <label
                            className="mb-1.5 block text-[11px] font-semibold uppercase tracking-wider text-muted"
                            htmlFor="email"
                          >
                            EMAIL
                          </label>
                          <input
                            id="email"
                            type="email"
                            required
                            autoFocus
                            value={email}
                            onChange={(event) => setEmail(event.target.value)}
                            placeholder="you@company.com"
                            className="h-11 w-full rounded-lg border border-line bg-bg px-4 text-sm text-fg placeholder:text-muted focus:border-accent focus:outline-none focus:ring-2 focus:ring-ring dark:border-white/20"
                          />
                        </div>

                        {error && (
                          <div aria-live="polite" className="text-xs font-medium text-red-500">
                            {error}
                          </div>
                        )}

                        <button
                          type="submit"
                          disabled={busy || !email.trim()}
                          className="inline-flex h-11 w-full items-center justify-center gap-2 rounded-lg bg-primary text-sm font-semibold text-primary-fg shadow-sm transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          {busy && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />}
                          <span>Continue &rarr;</span>
                        </button>
                      </form>

                      {/* OR Divider */}
                      <div className="relative my-5 flex items-center justify-center">
                        <div className="w-full border-t border-line" />
                        <span className="absolute bg-surface px-3 text-[11px] font-semibold uppercase tracking-widest text-muted">
                          OR
                        </span>
                      </div>

                      {/* Continue as guest */}
                      <Link
                        to="/workspace"
                        className="inline-flex h-11 w-full items-center justify-center gap-2 rounded-lg border border-line bg-surface/50 text-sm font-medium text-fg shadow-sm transition hover:border-line-strong hover:bg-surface"
                      >
                        <User className="h-4 w-4 text-muted" aria-hidden="true" />
                        <span>Continue as guest</span>
                      </Link>
                      <p className="mt-2.5 text-center text-xs text-muted">
                        Explore without an account. Sign in with email when you want to run research.
                      </p>
                    </div>
                  ) : (
                    <div>
                      {/* Step 2 Header */}
                      <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-accent">
                        <Mail className="h-4 w-4" aria-hidden="true" />
                        <span>STEP 2 OF 2</span>
                      </div>
                      <h2 className="mt-3 text-2xl font-bold tracking-tight text-fg">
                        Check your inbox
                      </h2>
                      <p className="mt-1.5 text-xs text-muted sm:text-sm">
                        We sent a 6-digit code to{" "}
                        <span className="font-semibold text-fg" title={email}>
                          {truncateEmail(email)}
                        </span>
                        . It expires in 10 minutes.
                      </p>

                      {/* Step 2 Form (Six separate digit boxes) */}
                      <form
                        onSubmit={(e) => {
                          e.preventDefault();
                          void verifyCode(digits.join(""));
                        }}
                        className="mt-6"
                      >
                        <div
                          className={`flex items-center justify-between gap-2 sm:gap-2.5 ${
                            shake ? "animate-shake" : ""
                          }`}
                        >
                          {digits.map((digit, idx) => (
                            <input
                              key={idx}
                              ref={(el) => {
                                digitRefs.current[idx] = el;
                              }}
                              type="text"
                              inputMode="numeric"
                              autoComplete="one-time-code"
                              pattern="\\d*"
                              maxLength={1}
                              value={digit}
                              onChange={(e) => handleDigitChange(idx, e.target.value)}
                              onKeyDown={(e) => handleKeyDown(idx, e)}
                              onPaste={handlePaste}
                              aria-label={`Digit ${idx + 1}`}
                              className="h-13 w-11 rounded-lg border border-line bg-bg text-center text-xl font-bold text-fg transition focus:border-accent focus:outline-none focus:ring-2 focus:ring-ring dark:border-white/20 sm:h-14 sm:w-12"
                            />
                          ))}
                        </div>

                        {error && (
                          <div
                            aria-live="polite"
                            className="mt-3 text-center text-xs font-medium text-red-500"
                          >
                            {error}
                          </div>
                        )}

                        {/* Under the boxes: Verify and sign in button */}
                        <button
                          type="submit"
                          disabled={busy || digits.some((d) => !d)}
                          className="mt-5 inline-flex h-11 w-full items-center justify-center gap-2 rounded-lg bg-primary text-sm font-semibold text-primary-fg shadow-sm transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          {busy && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />}
                          <span>Verify and sign in</span>
                        </button>

                        {/* Resend and change email row */}
                        <div className="mt-4 flex items-center justify-between text-xs text-muted">
                          {cooldown > 0 ? (
                            <span>Resend code in {cooldown}s</span>
                          ) : (
                            <button
                              type="button"
                              onClick={() => void sendCode()}
                              disabled={busy}
                              className="font-medium text-accent hover:underline disabled:opacity-50"
                            >
                              Resend code
                            </button>
                          )}
                          <button
                            type="button"
                            onClick={handleChangeEmail}
                            className="hover:text-fg hover:underline"
                          >
                            Change email
                          </button>
                        </div>
                      </form>
                    </div>
                  )}
                </div>
              </div>

              {/* Below the card on both steps */}
              <p className="mt-4 text-center text-xs text-muted">
                Protected by one-time codes
              </p>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
