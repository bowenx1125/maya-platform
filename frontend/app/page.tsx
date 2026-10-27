"use client";

import { useState } from "react";

import { AcademyMoodProvider } from "../components/academy/mood";
import {
  Burst,
  SignInBackdrop,
  SignInStage,
} from "../components/academy/sign-in-stage";
import { LoadingCard } from "../components/ui";
import { useT } from "../lib/i18n";
import { RegisterForm } from "../components/register-form";
import { LoginForm, useSession } from "../components/session-provider";

export default function HomePage() {
  const t = useT();
  const { status } = useSession();
  const [registering, setRegistering] = useState(false);
  const [step, setStep] = useState(1);
  // The same card guarded pages show while the session is being checked.
  if (status === "loading")
    return (
      <main className="shell">
        <LoadingCard />
      </main>
    );
  return (
    <AcademyMoodProvider>
      <main className="auth-arcade relative min-h-screen overflow-hidden bg-[#FFF7CC] bg-[repeating-conic-gradient(from_0deg_at_30%_78%,#FFE14D_0_7deg,#FFF7CC_7deg_14deg)] text-[#111]">
        <SignInBackdrop />
        <div className="relative mx-auto grid min-h-screen max-w-[1440px] grid-cols-[1.15fr_1fr] max-[767px]:grid-cols-1">
          {/* The picked card follows the registration step (2's "select"). */}
          <SignInStage picked={registering ? step : 1} />
          <section className="relative flex items-center justify-center px-12 py-14 max-[1100px]:px-8 max-[767px]:px-4 max-[767px]:pt-4 max-[767px]:pb-10">
            <div className="relative w-full max-w-[470px]">
              <Burst
                size={160}
                fill="#FF4D8D"
                className="-right-14 -bottom-14 rotate-12 max-[767px]:hidden"
              />
              <div className="auth-card relative rotate-[2deg] rounded-[24px] border-[5px] border-[#111] bg-white px-9 pt-[92px] pb-9 shadow-[14px_14px_0_#111] max-[767px]:rotate-0 max-[767px]:px-5 max-[767px]:pt-20">
                <span
                  aria-hidden="true"
                  className="absolute -top-4 left-10 h-8 w-28 -rotate-6 border-[3px] border-[#111] bg-[#67E8F9cc]"
                />
                <span
                  aria-hidden="true"
                  className="absolute -top-4 right-10 h-8 w-28 rotate-6 border-[3px] border-[#111] bg-[#FFE14Dcc]"
                />
                {/* The heading is the cast's speech bubble. */}
                <div className="absolute -top-14 -left-14 max-[1100px]:-left-6 max-[767px]:-top-10 max-[767px]:-left-1">
                  <h2 className="relative m-0 -rotate-[5deg] rounded-[28px] border-[5px] border-[#111] bg-[#FFE14D] px-7 py-3 font-display text-[46px] leading-none font-extrabold whitespace-nowrap shadow-[8px_8px_0_#111] after:absolute after:-bottom-[26px] after:left-10 after:h-0 after:w-0 after:border-t-[26px] after:border-r-[26px] after:border-t-[#111] after:border-r-transparent after:content-[''] max-[767px]:text-[32px]">
                    {registering ? t("registerTitle") : t("academyWelcome")}
                  </h2>
                </div>
                {registering ? (
                  <RegisterForm
                    onCancel={() => {
                      setRegistering(false);
                      setStep(1);
                    }}
                    onStepChange={setStep}
                  />
                ) : (
                  <LoginForm onRegister={() => setRegistering(true)} />
                )}
              </div>
            </div>
          </section>
        </div>
      </main>
    </AcademyMoodProvider>
  );
}
