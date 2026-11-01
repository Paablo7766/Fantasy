import { redirect } from "next/navigation";

// Ruta antigua: next.config.ts ya redirige; esto cubre la navegación del cliente.
export default function Page() {
  redirect("/equipo?tab=cartera");
}
