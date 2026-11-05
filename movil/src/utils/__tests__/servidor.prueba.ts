/**
 * A qué servidor le habla la app. Importa para usarla desde un celular: si la
 * dirección se deduce mal, la app parece caída aunque el servidor esté bien.
 */
import { deducirServidor, normalizarServidor } from "@/utils/servidor";

describe("normalizarServidor", () => {
  it("una IP sola se completa con http y el puerto del backend", () => {
    expect(normalizarServidor("192.168.1.20")).toBe("http://192.168.1.20:8000");
  });

  it("respeta el puerto si se escribe", () => {
    expect(normalizarServidor("192.168.1.20:9000")).toBe("http://192.168.1.20:9000");
  });

  it("limpia espacios, mayúsculas y la barra final", () => {
    expect(normalizarServidor("  HTTP://192.168.1.20:8000/ ")).toBe("http://192.168.1.20:8000");
  });

  it("con protocolo no adivina el puerto: puede estar detrás de un proxy", () => {
    expect(normalizarServidor("https://velvet.ejemplo.cl")).toBe("https://velvet.ejemplo.cl");
  });

  it("acepta un nombre de equipo", () => {
    expect(normalizarServidor("mi-pc.local")).toBe("http://mi-pc.local:8000");
  });

  it("rechaza lo que no es una dirección", () => {
    for (const malo of ["", "   ", "192.168.1 .20", "http://", "ftp://192.168.1.20", "192.168.1.20:99999", ".local"]) {
      expect(normalizarServidor(malo)).toBeNull();
    }
  });
});

describe("deducirServidor", () => {
  it("manda lo que escribió la persona", () => {
    const s = deducirServidor({
      guardado: "10.0.0.5",
      compilado: "http://192.168.1.20:8000",
      pagina: { protocolo: "http:", host: "localhost" },
    });
    expect(s).toEqual({ url: "http://10.0.0.5:8000", origen: "escrito" });
  });

  it("después, la que se fijó al compilar la APK", () => {
    expect(deducirServidor({ compilado: "http://192.168.1.20:8000" })).toEqual({
      url: "http://192.168.1.20:8000",
      origen: "compilado",
    });
  });

  it("en el navegador, el mismo computador que sirvió la página", () => {
    const s = deducirServidor({ pagina: { protocolo: "http:", host: "192.168.1.20" } });
    expect(s).toEqual({ url: "http://192.168.1.20:8000", origen: "pagina" });
  });

  it("en Expo Go, el computador desde el que se cargó la app", () => {
    const s = deducirServidor({ hostUri: "192.168.1.20:8081" });
    expect(s).toEqual({ url: "http://192.168.1.20:8000", origen: "expo" });
  });

  it("sin pistas, localhost como siempre", () => {
    expect(deducirServidor({})).toEqual({ url: "http://localhost:8000", origen: "local" });
    expect(deducirServidor({ hostUri: "localhost:8081" }).origen).toBe("local");
  });

  it("una dirección guardada inválida no deja a la app sin servidor", () => {
    expect(deducirServidor({ guardado: "esto no es una ip", hostUri: "192.168.1.20:8081" }).origen).toBe("expo");
  });
});
