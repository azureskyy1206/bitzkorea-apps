"use client";

import { usePathname } from "next/navigation";
import { isSalesManagementPath, isSalesPath, isSalesSupportPath } from "../lib/sales-nav-paths";
import SalesManagementSubNav from "./SalesManagementSubNav";
import SalesSubNav from "./SalesSubNav";
import SalesSupportSubNav from "./SalesSupportSubNav";

export default function SalesSectionNav() {
  const pathname = usePathname() || "";

  if (isSalesManagementPath(pathname)) return <SalesManagementSubNav />;
  if (isSalesSupportPath(pathname)) return <SalesSupportSubNav />;
  if (isSalesPath(pathname)) return <SalesSubNav />;
  return null;
}
