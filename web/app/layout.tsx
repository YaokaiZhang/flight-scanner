import type { Metadata } from "next";
import { JetBrains_Mono, Playfair_Display } from "next/font/google";
import { Nav } from "@/components/Nav";
import { WatchAssistant } from "@/components/WatchAssistant";
import "./globals.css";

const mono = JetBrains_Mono({ subsets: ["latin"], weight: ["300", "400", "500"], variable: "--mono" });
const script = Playfair_Display({ subsets: ["latin"], weight: "700", style: "italic", variable: "--script" });

export const metadata: Metadata = {
  title: "Flight Scanner",
  description: "Deals measured against their Baseline.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${mono.variable} ${script.variable}`}>
      <body>
        <a className="skip" href="#main">Skip to content</a>
        <div className="workspace">
          <Nav />
          {children}
        </div>
        <div className="sky-coordinate" style={{ bottom: 10, left: 140 }}>
          verda · localhost · via SSH tunnel
        </div>
        <WatchAssistant />
      </body>
    </html>
  );
}
