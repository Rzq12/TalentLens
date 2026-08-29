import type { Metadata, Viewport } from "next";
import { Archivo, Archivo_Narrow, Azeret_Mono } from "next/font/google";
import "./globals.css";
import { RegisterRail } from "@/components/shell/RegisterRail";
import { ThreadProvider } from "@/components/thread/ThreadProvider";

const archivo = Archivo({
  variable: "--font-archivo",
  subsets: ["latin"],
  display: "swap",
});

const archivoNarrow = Archivo_Narrow({
  variable: "--font-archivo-narrow",
  subsets: ["latin"],
  display: "swap",
});

const azeret = Azeret_Mono({
  variable: "--font-azeret",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "TalentLens — Evidence Register",
  description:
    "Rank, explain and recommend candidates at scale without ever rejecting one. Every score traces to a cited span.",
};

export const viewport: Viewport = {
  themeColor: "#e9ebe3",
};

const DIRECTION_CONTRACT = `
THESIS: The system never decides, it records; this is an evidence register, refusing the ATS dashboard of sidebar, stat cards and blue accent.
OWN-WORLD: Olive form paper, three declared rule weights, stamp violet accent, seal red alarm; ruled sheets and seal blocks, never cards, radius 2px.
STORY: A recruiter hours deep sees a ranking she can defend, believes every figure traces to a cited span, pulls the thread, and files her override with a reason.
FIRST VIEWPORT: Ruled masthead, run identity left and CHAIN INTACT seal block right; full-width ledger beneath with no container; 64px sequence gutter carrying tabular ordinals and a continuity tick that breaks at overrides; primary action stamped top right.
FORM: Chain of Custody, candidate five of seven, seed 15a0b80a.
FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
`;

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${archivo.variable} ${archivoNarrow.variable} ${azeret.variable} h-full antialiased`}
    >
      <body className="flex min-h-full flex-col">
        <div
          hidden
          dangerouslySetInnerHTML={{ __html: `<!--${DIRECTION_CONTRACT}-->` }}
        />
        <ThreadProvider>
          <a
            href="#register-main"
            className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:bg-stamp focus:px-3 focus:py-2 focus:text-leaf focus:no-underline"
          >
            Skip to register
          </a>
          <div className="flex min-h-screen">
            <RegisterRail />
            <main
              id="register-main"
              className="min-w-0 flex-1 border-l border-rule-entry bg-paper"
            >
              {children}
            </main>
          </div>
        </ThreadProvider>
      </body>
    </html>
  );
}
