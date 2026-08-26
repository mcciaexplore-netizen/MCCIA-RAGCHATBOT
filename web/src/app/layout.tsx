import type { Metadata } from "next";
import { Bricolage_Grotesque, Outfit } from "next/font/google";
import Image from "next/image";
import Link from "next/link";
import "./globals.css";

const bricolageGrotesque = Bricolage_Grotesque({
  variable: "--font-heading",
  subsets: ["latin"],
  weight: ["400", "700", "800"],
});

const outfit = Outfit({
  variable: "--font-body",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
});

export const metadata: Metadata = {
  title: "MCCIA Google",
  description: "Ask questions or browse 70+ years of MCCIA's Sampada magazine archive.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${bricolageGrotesque.variable} ${outfit.variable} h-full antialiased`}
    >
      <body className="flex min-h-full flex-col bg-brand-bg text-brand-text">
        <header className="border-b border-brand-accent bg-brand-surface">
          <div className="flex w-full items-center justify-between px-12 py-3 sm:px-20">
            <Link href="/" className="flex items-center">
              <Image src="/mccia-logo.png" alt="MCCIA" width={178} height={48} className="h-9 w-auto" priority />
            </Link>
            <nav className="flex items-center gap-8 text-sm font-medium">
              <Link href="/archive" className="text-brand-primary hover:text-brand-primary-hover">
                Browse Issues
              </Link>
              <span className="text-brand-text-muted">About</span>
              <span className="text-brand-text-muted">How it works</span>
              <span className="text-brand-text-muted">Help</span>
            </nav>
          </div>
        </header>
        <main className="flex flex-1 flex-col">{children}</main>
      </body>
    </html>
  );
}
