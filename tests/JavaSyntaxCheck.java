import com.sun.source.util.JavacTask;
import javax.tools.*;
import java.io.File;
import java.util.*;

/** Parses every native source at the APK's language level (Java 8). Catches syntax errors that
 * host tests miss when they stub a class; no Android SDK needed. Run: java JavaSyntaxCheck.java <dir>... */
public final class JavaSyntaxCheck {
 public static void main(String[] args)throws Exception{
  List<File> files=new ArrayList<>();
  for(String dir:args)collect(new File(dir),files);
  if(files.isEmpty())throw new AssertionError("no Java sources under "+Arrays.toString(args));
  JavaCompiler compiler=ToolProvider.getSystemJavaCompiler();
  DiagnosticCollector<JavaFileObject> diagnostics=new DiagnosticCollector<>();
  try(StandardJavaFileManager manager=compiler.getStandardFileManager(diagnostics,Locale.ROOT,null)){
   JavacTask task=(JavacTask)compiler.getTask(null,manager,diagnostics,Arrays.asList("--release","8","-proc:none"),null,manager.getJavaFileObjectsFromFiles(files));
   task.parse();
  }
  int errors=0;
  for(Diagnostic<? extends JavaFileObject> d:diagnostics.getDiagnostics())
   if(d.getKind()==Diagnostic.Kind.ERROR){errors++;System.err.println(d);}
  if(errors>0)throw new AssertionError(errors+" syntax error(s)");
  System.out.println("PASS java syntax: "+files.size()+" native sources parse at Java 8");
 }
 static void collect(File f,List<File> out){
  File[] list=f.listFiles();
  if(list==null){if(f.getName().endsWith(".java"))out.add(f);return;}
  Arrays.sort(list);
  for(File c:list)collect(c,out);
 }
}
