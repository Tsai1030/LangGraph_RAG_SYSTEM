// AuthShell 由各 page 自行 import 使用，layout 純粹 pass-through。
// 保留此檔案讓 Next.js 識別 (auth) 群組，未來若要加 auth 群組共用 provider 也方便。
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
