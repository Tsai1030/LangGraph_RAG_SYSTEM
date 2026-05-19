import type { Metadata } from "next";
import { Geist, Geist_Mono, Instrument_Serif, JetBrains_Mono, Noto_Serif_TC } from "next/font/google";
import { TooltipProvider } from "@/components/ui/tooltip";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });
const instrumentSerif = Instrument_Serif({
  variable: "--font-serif",
  subsets: ["latin"],
  weight: ["400"],
  style: ["normal", "italic"],
});
const jetbrainsMono = JetBrains_Mono({
  variable: "--font-mono-jb",
  subsets: ["latin"],
  weight: ["400", "500"],
});
// Traditional Chinese editorial serif — used on the sidebar brand title.
// Google Fonts serves CJK via unicode-range so only the actual glyphs
// we render get downloaded; bundle impact stays modest.
const notoSerifTC = Noto_Serif_TC({
  variable: "--font-serif-tc",
  weight: ["500", "700"],
});

export const metadata: Metadata = {
  title: "營造知識助理",
  description: "內部員工知識查詢系統，RAG 智能問答與表單生成",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-TW" className={`${geistSans.variable} ${geistMono.variable} ${instrumentSerif.variable} ${jetbrainsMono.variable} ${notoSerifTC.variable} h-full`}>
      <body className="min-h-full flex flex-col antialiased">
        <TooltipProvider delay={400}>
          {children}
        </TooltipProvider>
      </body>
    </html>
  );
}
