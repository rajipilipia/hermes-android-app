import {it,expect} from "vitest";import {readFileSync} from "node:fs";
it("bundled HTTPS page uses the chosen server origin required by its websocket Origin guard",()=>{
 const main=readFileSync("android/src/us/pilipia/hermes/prototype/MainActivity.java","utf8");
 const policy=readFileSync("android/src/us/pilipia/hermes/prototype/NativeHostPolicy.java","utf8");
 // No server is compiled in: the page origin is the saved, native-validated server or the setup origin.
 expect(main).not.toContain("pilipia.us\"");expect(policy).not.toContain("gateway.example.com");
 expect(main).toContain("server=servers.load();");
 expect(main).toContain("NativeHostPolicy.useOrigin(server!=null?server:ServerOrigin.SETUP);");
 expect(main).toContain("web.loadUrl(NativeHostPolicy.appUrl());");
 expect(policy).toContain('return origin+"/assets/index.html";');
 expect(main).toContain('getAssets().open("www/"+path)');expect(main).toContain('return blocked()');
});
