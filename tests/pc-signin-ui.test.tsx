// @vitest-environment jsdom
import {it,expect,vi} from "vitest";
import {render,screen,fireEvent,waitFor,cleanup} from "@testing-library/react";
import {App} from "../src/App";import {ChatController} from "../src/chat";import {Peer} from "./fixture";
it("primary PC sign-in uses native auth, never manual token fields",async()=>{
 const c=new ChatController(new Peer().client());const connect=vi.spyOn(c,"connectPc").mockResolvedValue();
 render(<App controller={c}/>);expect((screen.getByLabelText("Gateway endpoint") as HTMLInputElement).value).toBe("wss://gateway.example.com/api/ws");
 fireEvent.click(screen.getByRole("button",{name:"Sign in to this PC"}));await waitFor(()=>expect(connect).toHaveBeenCalledTimes(1));cleanup();
});
